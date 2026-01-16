from django.contrib import admin
from django.contrib.auth import get_user_model

CustomUser = get_user_model()


# Register your models here.
@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    list_display = ("username", "email", "role", "is_active", "last_login")
    list_filter = ("role", "is_active")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("-last_login",)
