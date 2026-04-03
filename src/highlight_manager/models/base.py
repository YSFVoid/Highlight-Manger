from pydantic import BaseModel, ConfigDict


class AppModel(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
        validate_assignment=True,
    )
