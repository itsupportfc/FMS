from django import template

register = template.Library()


# Filters transform values and are applied with | in templates
@register.filter
def add_class(field, css_class):
    """Add CSS classes to a form field's widget."""
    if hasattr(field, "field"):
        field_obj = field.field
    else:
        field_obj = field

    # Render the field and add the class attribute
    rendered = str(field)

    # Check if the field already has a class attribute
    if "class=" in rendered:
        # Replace existing class attribute, appending our classes
        rendered = rendered.replace('class="', f'class="{css_class} ')
    else:
        # Add class attribute before the closing >
        rendered = rendered.replace("/>", f' class="{css_class}"/>').replace(
            ">",
            f' class="{css_class}">',
            1,  # Only replace the first occurrence (the opening tag)
        )

    from django.utils.safestring import mark_safe

    return mark_safe(rendered)
