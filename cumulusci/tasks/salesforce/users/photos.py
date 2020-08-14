import re
import base64
import pathlib
import json
from typing import Dict

from cumulusci.tasks.salesforce import BaseSalesforceApiTask
from cumulusci.core.exceptions import CumulusCIException
from simple_salesforce.exceptions import SalesforceMalformedRequest


def join_errors(e: SalesforceMalformedRequest) -> str:
    "; ".join([error.get("message", "Unknown error.") for error in e.content])


class UploadProfilePhoto(BaseSalesforceApiTask):
    task_docs = """
    Uploads a profile photo for the default CumulusCI user.

    Example
    *******

    Upload a user profile photo for a user whose ``Alias`` equals ``grace``.:: yaml

        tasks:
            upload_profile_photo:
                group: Internal storytelling data
                class_path: cumulusci.tasks.salesforce.UploadDefaultUserProfilePhoto
                description: Uploads profile photo for the default user.
                options:
                    photo_path: datasets/users/default/profile.png
    """

    task_options = {
        "photo": {"description": "Path to user's profile photo.", "required": True},
        "where": {
            "description": """WHERE clause when querying for which User to upload the profile photo for.
            - Don't prefix with ``WHERE ``
            - The SOQL query must return one and only one User record.
            - If no "where" is supplied, uploads the photo for the org's default User.
            """,
            "required": False,
        },
    }

    def _raise_cumulusci_exception(self, e: SalesforceMalformedRequest) -> None:
        raise CumulusCIException(join_errors(e))

    def _get_user_fields(self) -> Dict[str, str]:
        user_fields = {}
        for field in self.sf.User.describe()["fields"]:
            user_fields[field["name"]] = field
        return user_fields

    def _get_query(self, filters: Dict[str, object]) -> str:
        user_fields = self._get_user_fields()
        string_soap_types = ("xsd:string", "tns:ID", "urn:address")

        query_filters = []
        for name, value in filters.items():
            field = user_fields.get(name)

            # Validate field exists.
            if not field:
                raise CumulusCIException(
                    f'User Field "{name}" referenced in "filters" option is not found.  Fields are case-sensitive.'
                )

            # Validate we can filter by field.
            if not field["filterable"]:
                raise CumulusCIException(
                    f'User Field "{name}" referenced in "filters" option must be filterable.'
                )

            if field["soapType"] in string_soap_types:
                query_filters.append(f"{name} = '{value}'")
            else:
                query_filters.append(f"{name} = {value}")

        return "SELECT Id FROM User WHERE {}".format(" AND ".join(query_filters))

    def _get_user_id_by_query(self, where: str) -> str:
        # Query for the User.
        query = "SELECT Id FROM User WHERE {}".format(
            re.sub(r"^WHERE ?", "", where, flags=re.I)
        )
        self.logger.info(f"Querying User: {query}")

        user_ids = []
        try:
            for record in self.sf.query_all(query)["records"]:
                user_ids.append(record["Id"])
        except SalesforceMalformedRequest as e:
            self._raise_cumulusci_exception(e)

        # Validate only 1 User found.
        if len(user_ids) < 1:
            raise CumulusCIException("No Users found.")
        if 1 < len(user_ids):
            raise CumulusCIException(
                "More than one User found ({}): {}".format(
                    len(user_ids), ", ".join(user_ids)
                )
            )

        # Log and return User ID.
        self.logger.info(f"Uploading profile photo for the User with ID {user_ids[0]}")
        return user_ids[0]

    def get_default_user_id(self) -> str:
        user_id = self.sf.restful("")["identity"][-18:]
        self.logger.info(
            f"Uploading profile photo for the default User with ID {user_id}"
        )
        return user_id

    def _insert_content_document(self) -> str:
        """

        """
        path = pathlib.Path(self.options["photo"])

        if not path.exists():
            raise CumulusCIException(f"No photo found at path: {path}")

        self.logger.info(f"Setting user photo to {path}")
        result = self.sf.ContentVersion.create(
            {
                "PathOnClient": path.name,
                "Title": path.stem,
                "VersionData": base64.b64encode(path.read_bytes()).decode("utf-8"),
            }
        )
        if not result["success"]:
            raise CumulusCIException(
                "Failed to create photo ContentVersion: {}".format(result["errors"])
            )
        content_version_id = result["id"]

        # Query the ContentDocumentId for our created record.
        content_document_id = self.sf.query(
            f"SELECT Id, ContentDocumentId FROM ContentVersion WHERE Id = '{content_version_id}'"
        )["records"][0]["ContentDocumentId"]

        self.logger.info(
            f"Uploaded profile photo ContentDocument {content_document_id}"
        )

        return content_document_id

    def _delete_content_document(self, content_document_id):
        self.sf.ContentDocument.delete(content_document_id)

    def _run_task(self):
        # Get the User Id of the targeted user.
        # Validates only one user is found.
        user_id = (
            self._get_user_id_by_query(self.options["where"])
            if self.options.get("where")
            else self._get_default_user_id()
        )

        content_document_id = self._insert_content_document()

        # Call the Connect API to set our user photo.
        try:
            self.sf.restful(
                f"connect/user-profiles/{user_id}/photo",
                data=json.dumps({"fileId": content_document_id}),
                method="POST",
            )
        except SalesforceMalformedRequest as e:
            self.logger.error(
                "An error occured setting the ContentDocument as the users's profile photo."
            )
            self.logger.error(f"Deleting ContentDocument {content_document_id}")
            self._delete_content_document(content_document_id)
            self._raise_cumulusci_exception(e)
