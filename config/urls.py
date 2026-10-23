from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.conf.urls.static import static
from marketplace.views import health
from marketplace import views as marketplace_views
from marketplace.admin_views import delete_previews, marketplace_analytics, marketplace_pulse, marketplace_search
from marketplace.review_centre import review_centre

urlpatterns = [
    path(
        "admin/marketplace-analytics/",
        admin.site.admin_view(marketplace_analytics),
        name="marketplace_admin_analytics",
    ),
    path(
        "admin/marketplace-search/",
        admin.site.admin_view(marketplace_search),
        name="marketplace_admin_search",
    ),
    path(
        "admin/marketplace-pulse/",
        admin.site.admin_view(marketplace_pulse),
        name="marketplace_admin_pulse",
    ),
    path("admin/login/", marketplace_views.AdminLoginView.as_view(), name="admin_login"),
    path("admin/review/", admin.site.admin_view(review_centre), name="marketplace_review_centre"),
    path("admin/previews/delete/", admin.site.admin_view(delete_previews), name="marketplace_delete_previews"),
    path("admin/", admin.site.urls),
    path("", include("commerce.urls")),
    path("", include("marketplace.urls")),
    path("health/", health, name="health"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
