from typing import Any

from rest_framework import serializers

from gmp.config import Configurations
from gmp_apps.member_documents.dataclasses.request.create.create_document import CreateDocumentRequest
from gmp_apps.member_documents.models import DocumentType


class CreateDocumentRequestSerializer(serializers.Serializer):
    document_type = serializers.ChoiceField(choices=DocumentType.choices)
    file = serializers.FileField(allow_empty_file=False, max_length=200)
    label = serializers.CharField(required=False, allow_blank=True, max_length=100, default='')

    def validate_file(self, value: Any) -> Any:
        if value.size > Configurations.member_document_max_bytes:
            raise serializers.ValidationError(f'The file is too large (limit {Configurations.member_document_max_bytes // 1_000_000} MB)')
        return value

    def create(self, validated_data: dict[str, Any]) -> CreateDocumentRequest:
        return CreateDocumentRequest(**validated_data)
