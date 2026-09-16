from pydantic import BaseModel, EmailStr, Field
from typing import Optional

class ClientCreate(BaseModel):
    name: str = ""
    first_name: str = ""
    last_name: str = ""
    phone: str = ""
    email: str = ""

class AppointmentCreate(BaseModel):
    client_id: str
    date: str
    time: str
    service: str = "Coupe"
    source: str = "site"
    notes: str = ""

class AppointmentPatch(BaseModel):
    date: Optional[str] = None
    time: Optional[str] = None
    service: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None

class ClosureCreate(BaseModel):
    date: str
    time: Optional[str] = None
    reason: str = ""
