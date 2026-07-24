"""Service for handling Gmail attachments and uploading them to Firebase Storage."""

import base64
import uuid
from firebase_admin import storage
from gmail_service import gmail_service


class AttachmentService:
    def extract_and_upload(self, message_id: str, attachment_id: str, filename: str, mime_type: str) -> str:
        """
        Fetches a MIME attachment from Gmail, decodes it, and uploads it to Firebase Storage.
        Returns the public URL of the uploaded file.
        """
        if not gmail_service.service:
            print("Gmail API service is not initialized")
            return ""

        # 1. Fetch attachment payload from Gmail API
        try:
            attachment = gmail_service.service.users().messages().attachments().get(
                userId="me",
                messageId=message_id,
                id=attachment_id
            ).execute()
        except Exception as e:
            print(f"Failed to fetch attachment {attachment_id} from Gmail: {e}")
            return ""

        file_data = attachment.get("data")
        if not file_data:
            return ""

        # 2. Decode the URL-safe base64 data
        try:
            decoded_bytes = base64.urlsafe_b64decode(file_data)
        except Exception as e:
            print(f"Failed to decode base64 data for attachment {filename}: {e}")
            return ""

        # 3. Upload to Firebase Storage
        try:
            # Uses the default bucket configured in your app.py firebase_admin initialization
            bucket = storage.bucket()

            # Generate a unique path to prevent naming collisions
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            blob_path = f"support_attachments/{message_id}/{unique_filename}"

            blob = bucket.blob(blob_path)
            blob.upload_from_string(
                decoded_bytes,
                content_type=mime_type
            )

            # Make the blob publicly accessible for the Flutter client
            blob.make_public()

            return blob.public_url

        except Exception as e:
            print(f"Failed to upload attachment {filename} to Firebase Storage: {e}")
            return ""


attachment_service = AttachmentService()