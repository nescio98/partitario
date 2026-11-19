"""Unfold's form styling for the allauth pages (templates/allauth/elements/)."""

from django import template
from django.forms import BoundField
from django.utils.safestring import SafeString
from unfold.widgets import CHECKBOX_CLASSES, INPUT_CLASSES

register = template.Library()


@register.simple_tag
def input_classes(input_type: str = "text") -> str:
    """The classes Unfold gives its own widgets, already in its stylesheet."""
    return " ".join(CHECKBOX_CLASSES if input_type in ("checkbox", "radio") else INPUT_CLASSES)


@register.filter
def styled(field: BoundField) -> SafeString:
    """Render a form field's widget with Unfold's classes."""
    if field.widget_type == "turnstile":
        return field.as_widget()  # Cloudflare's own markup: its class is the hook of its script
    input_type = getattr(field.field.widget, "input_type", "text")
    return field.as_widget(attrs={"class": input_classes(input_type)})
