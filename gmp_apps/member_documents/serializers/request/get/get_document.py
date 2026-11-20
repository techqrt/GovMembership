from typing import Any

from rest_framework import serializers

from gmp_apps.member_documents.dataclasses.request.get.get_document import GetDocumentRequest


class GetDocumentRequestSerializer(serializers.Serializer):
    document_id = serializers.IntegerField(min_value=1)

    def create(self, validated_data: dict[str, Any]) -> GetDocumentRequest:
        return GetDocumentRequest(**validated_data)
