from django.apps import AppConfig

class MarketplaceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "marketplace"

    def ready(self):
        from . import checks  # noqa: F401  (registers deployment checks)
        from django.core.cache import cache
        from django.db.models.signals import post_delete, post_save

        from .catalog import CATEGORY_MENU_CACHE_KEY
        from .models import Category, Product

        def refresh_category_menu(**kwargs):
            # New approvals, edits and deletions show in the category menu straight away.
            cache.delete(CATEGORY_MENU_CACHE_KEY)

        for model in (Product, Category):
            post_save.connect(refresh_category_menu, sender=model, dispatch_uid=f"menu-save-{model.__name__}")
            post_delete.connect(refresh_category_menu, sender=model, dispatch_uid=f"menu-delete-{model.__name__}")
