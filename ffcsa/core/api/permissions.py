from rest_framework import permissions


class IsOwner(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        return obj == request.user


class CanPay(permissions.BasePermission):

    def has_permission(self, request, view):
        return view.action == 'non_member_payment' or request.user.is_authenticated

