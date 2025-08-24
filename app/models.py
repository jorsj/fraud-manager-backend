from pydantic import BaseModel, Field, ConfigDict

# Pydantic models provide automatic data validation, serialization, and documentation.


class IgnoreExtraFieldsModel(BaseModel):
    """
    A base model configured to ignore any extra fields that are not defined.
    All other models will inherit from this to share the behavior.
    """

    model_config = ConfigDict(extra="ignore")


class TelephonyPayload(IgnoreExtraFieldsModel):
    """
    Represents the 'telephony' object within the Dialogflow payload.
    """

    caller_id: str


class DialogflowPayload(IgnoreExtraFieldsModel):
    """
    Represents the 'payload' object from Dialogflow, containing telephony info.
    """

    telephony: TelephonyPayload


class CheckRequest(IgnoreExtraFieldsModel):
    """
    Defines the expected request body for the /check/ endpoint.
    """

    payload: DialogflowPayload


class QueryParameters(IgnoreExtraFieldsModel):
    """
    Represents the 'parameters' object within Dialogflow's sessionInfo.
    """

    national_id: str


class SessionInfo(IgnoreExtraFieldsModel):
    """
    Represents the 'sessionInfo' object from Dialogflow.
    Using an alias to allow the incoming JSON to use 'sessionInfo' (camelCase)
    while the Python code uses 'session_info' (snake_case).
    """

    parameters: QueryParameters


class QueryRequest(IgnoreExtraFieldsModel):
    """
    Defines the expected request body for the /query/ endpoint.
    """

    payload: DialogflowPayload
    session_info: SessionInfo = Field(..., alias="sessionInfo")
