from django.conf.urls import url

from ..views.admin import UserAdminAPI, GenerateUserAPI

# 这一层用于将请求翻译，以调用views的方法
urlpatterns = [
    url(r"^user/?$", UserAdminAPI.as_view(), name="user_admin_api"),
    url(r"^generate_user/?$", GenerateUserAPI.as_view(), name="generate_user_api"),
]
