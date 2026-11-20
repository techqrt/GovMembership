from django.urls import path

from gmp_apps.member_documents.controllers.document import MemberDocumentViewController as Document

urlpatterns = [
    path('document/create/', Document.create, name='create_member_documents_document'),
    path('document/get/', Document.get, name='get_member_documents_document'),
    path('document/get_all/', Document.get_all, name='get_all_member_documents_document'),
    path('document/delete/', Document.delete, name='delete_member_documents_document'),
    path('document/download/', Document.download, name='download_member_documents_document'),
]
