import logging
from pathlib import Path

import allauth.headless.spec.internal.schema
import yaml


def merge_allauth_schema_hook(result, generator, request, public):
    """
    Merge django-allauth headless API schema into the main drf-spectacular schema.

    This postprocessing hook runs at the end of schema generation to combine
    the allauth headless authentication endpoints with the Paperless-ngx API
    documentation, creating a unified API documentation experience.

    Args:
        result: The generated OpenAPI schema dict
        generator: The schema generator instance
        request: The HTTP request (if available)
        public: Whether this is a public schema generation

    Returns:
        The modified schema dict with allauth endpoints merged in
    """
    try:
        allauth_schema = _get_allauth_schema()
    except Exception as e:
        # If allauth schema generation fails, log and continue without it
        # to avoid breaking the entire schema generation
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to load allauth schema: {e}")
        return result

    # Merge paths - these are the actual API endpoints
    if "paths" in allauth_schema:
        # Ensure all operations have operationId (required by drf-spectacular)
        _ensure_operation_ids(allauth_schema["paths"])
        result["paths"].update(allauth_schema["paths"])

    # Merge components (schemas, responses, parameters, examples, etc.)
    if "components" in allauth_schema:
        for component_type, components in allauth_schema["components"].items():
            if component_type not in result["components"]:
                result["components"][component_type] = {}
            result["components"][component_type].update(components)

    # Merge tags - these organize endpoints in the documentation
    if "tags" in allauth_schema:
        existing_tag_names = {tag["name"] for tag in result.get("tags", [])}
        for tag in allauth_schema["tags"]:
            if tag["name"] not in existing_tag_names:
                result.setdefault("tags", []).append(tag)

    # Merge x-tagGroups (Redoc-specific feature for grouping tags)
    if "x-tagGroups" in allauth_schema:
        result.setdefault("x-tagGroups", []).extend(allauth_schema["x-tagGroups"])

    return result


def _ensure_operation_ids(paths):
    """
    Ensure all operations in the paths have operationId fields.

    drf-spectacular requires operationId on all operations. The allauth schema
    doesn't include them, so we generate them based on the path and method.

    Args:
        paths: The paths dict from the OpenAPI schema
    """
    http_methods = ["get", "post", "put", "patch", "delete", "head", "options", "trace"]

    for path, path_spec in paths.items():
        for method in http_methods:
            if method in path_spec and isinstance(path_spec[method], dict):
                operation = path_spec[method]
                if "operationId" not in operation:
                    # Generate operationId from path and method
                    # e.g., /api/auth/browser/v1/auth/login POST -> allauth_browser_auth_login_create
                    path_parts = [
                        p for p in path.split("/") if p and not p.startswith("{")
                    ]
                    # Remove 'api', 'auth', 'v1' as they're redundant
                    path_parts = [
                        p for p in path_parts if p not in ["api", "auth", "v1"]
                    ]
                    operation_id = "allauth_" + "_".join(path_parts)
                    # Add method suffix for clarity
                    method_suffix = {
                        "get": "retrieve" if "{" in path else "list",
                        "post": "create",
                        "put": "update",
                        "patch": "partial_update",
                        "delete": "destroy",
                    }.get(method, method)
                    operation_id += f"_{method_suffix}"
                    operation["operationId"] = operation_id


def _get_allauth_schema():
    """
    Load and customize the allauth headless API schema.

    This is a simplified version of allauth.headless.spec.internal.schema.get_schema()
    that doesn't require the allauth spec URLs to be registered, since we're merging
    the schema into drf-spectacular's output instead of serving it separately.

    Returns:
        dict: The processed allauth OpenAPI schema
    """
    # Find the allauth schema file dynamically based on the installed package location
    schema_path = (
        Path(allauth.headless.spec.internal.schema.__file__).parent.parent
        / "doc/openapi.yaml"
    )

    with schema_path.open("rb") as f:
        spec = yaml.safe_load(f)

    # Load description
    description_path = schema_path.parent / "description.md"
    with description_path.open("rb") as f:
        spec["info"]["description"] = f.read().decode("utf8")

    # Adjust paths to match our URL structure (/api/auth/ instead of /_allauth/)
    _adjust_allauth_paths(spec)

    # Apply allauth's schema customization functions that don't require URL reversing
    _apply_allauth_customizations(spec)

    return spec


def _adjust_allauth_paths(spec):
    """
    Adjust allauth paths from /_allauth/ to /api/auth/ to match paperless-ngx URLs.
    """
    from allauth.headless import app_settings

    paths = spec["paths"].items()
    spec["paths"] = {}

    # Replace /_allauth/ with /api/auth/ in all paths
    for path, path_spec in paths:
        new_path = path.replace("/_allauth/", "/api/auth/")

        # Handle client parameter - if only one client is configured, remove {client} from path
        if len(app_settings.CLIENTS) == 1:
            client_value = app_settings.CLIENTS[0]
            new_path = new_path.replace("{client}", client_value)
            # Also remove client parameters from the spec
            _remove_client_parameter(path_spec)

        spec["paths"][new_path] = path_spec


def _remove_client_parameter(path_spec):
    """
    Remove the {client} parameter from path and operation specs when only one client is configured.
    """
    # Remove from path-level parameters
    if "parameters" in path_spec:
        path_spec["parameters"] = [
            p
            for p in path_spec["parameters"]
            if not (
                isinstance(p, dict)
                and p.get("$ref") == "#/components/parameters/Client"
            )
        ]
        if not path_spec["parameters"]:
            del path_spec["parameters"]

    # Remove from operation-level parameters
    http_methods = ["get", "post", "put", "delete", "options", "head", "patch", "trace"]
    for method in http_methods:
        if (
            method in path_spec
            and isinstance(path_spec[method], dict)
            and "parameters" in path_spec[method]
        ):
            path_spec[method]["parameters"] = [
                p
                for p in path_spec[method]["parameters"]
                if not (
                    isinstance(p, dict)
                    and p.get("$ref") == "#/components/parameters/Client"
                )
            ]
            if not path_spec[method]["parameters"]:
                del path_spec[method]["parameters"]


def _apply_allauth_customizations(spec):
    """
    Apply allauth-specific schema customizations based on project configuration.

    This includes:
    - Removing paths for disabled features (MFA, social accounts, etc.)
    - Customizing signup fields based on ACCOUNT_SIGNUP_FIELDS
    - Removing unused tags and components
    """
    from allauth.core.internal.urlkit import script_aware_resolve
    from allauth.headless import app_settings
    from django.urls.exceptions import Resolver404

    # Drop paths that aren't actually available based on configuration
    used_tags = set()
    paths_to_remove = []

    for path, path_spec in spec["paths"].items():
        # Try to resolve the path - if it doesn't exist, mark for removal
        found_path = False
        for client in app_settings.CLIENTS:
            try:
                # Adjust path back to allauth format for resolution check
                test_path = path.replace("/api/auth/", "/_allauth/")
                if "{client}" not in test_path:
                    test_path = test_path.replace(f"/{client}/", "/{client}/")
                script_aware_resolve(test_path.replace("{client}", client))
                found_path = True
                break
            except (Resolver404, Exception):
                pass

        if found_path:
            # Collect tags from this path
            for method, method_spec in path_spec.items():
                if isinstance(method_spec, dict) and "tags" in method_spec:
                    used_tags.update(method_spec["tags"])
        else:
            paths_to_remove.append(path)

    # Remove unavailable paths
    for path in paths_to_remove:
        spec["paths"].pop(path)

    # Remove unused tags
    if "tags" in spec:
        spec["tags"] = [tag for tag in spec["tags"] if tag["name"] in used_tags]

    # Remove unused tag groups
    if "x-tagGroups" in spec:
        spec["x-tagGroups"] = [
            group
            for group in spec["x-tagGroups"]
            if any(tag in used_tags for tag in group["tags"])
        ]

    # Remove Client parameter from components if only one client
    if (
        len(app_settings.CLIENTS) == 1
        and "components" in spec
        and "parameters" in spec["components"]
    ):
        spec["components"]["parameters"].pop("Client", None)
