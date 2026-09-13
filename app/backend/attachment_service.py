"""Safe Gmail attachment retrieval for Support Center administrators.

The comparison branch uploaded attachments as public Storage objects. That
would expose potentially sensitive support files, so this service preserves
the retrieval capability without creating public URLs or durable copies.
"""

from gmail_service import gmail_service


class AttachmentService:
    MAX_BYTES = 10 * 1024 * 1024

    def extract(self, message_id: str, attachment_id: str) -> bytes:
        data = gmail_service.get_attachment(message_id, attachment_id)
        if len(data) > self.MAX_BYTES:
            raise ValueError("Attachment exceeds the 10 MB limit")
        return data


attachment_service = AttachmentService()
