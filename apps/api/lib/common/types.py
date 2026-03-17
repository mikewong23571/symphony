from dataclasses import dataclass


@dataclass(slots=True)
class ServiceInfo:
    name: str
    version: str
