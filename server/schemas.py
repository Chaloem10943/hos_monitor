from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentIdentity(BaseModel):
    machine_id: str = Field(min_length=8, max_length=128)
    hostname: str = Field(min_length=1, max_length=255)
    asset_tag: str = Field(default="", max_length=100)
    department: str = Field(default="", max_length=200)
    agent_version: str = Field(default="", max_length=32)
    wallpaper_revision: str = Field(default="", max_length=128)
    wallpaper_status: str = Field(default="", max_length=32)
    wallpaper_error: str = Field(default="", max_length=500)
    agent_update_release_id: int | None = Field(default=None, ge=1)
    agent_update_status: str = Field(default="", max_length=32)
    agent_update_error: str = Field(default="", max_length=500)


class HeartbeatRequest(AgentIdentity):
    pass


class DiskInfo(BaseModel):
    device_id: str = Field(min_length=1, max_length=32)
    label: str = Field(default="", max_length=200)
    total_bytes: int = Field(default=0, ge=0)
    free_bytes: int = Field(default=0, ge=0)


class NetworkInfo(BaseModel):
    adapter_name: str = Field(min_length=1, max_length=255)
    mac_address: str = Field(default="", max_length=64)
    ipv4: str = Field(min_length=7, max_length=45)
    is_primary: bool = False


class SoftwareInfo(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    version: str = Field(default="", max_length=200)
    publisher: str = Field(default="", max_length=500)
    install_date: str = Field(default="", max_length=32)


class MonitorObservation(BaseModel):
    monitor_type: str = Field(min_length=1, max_length=100)
    schema_version: int = Field(default=1, ge=1)
    observed_at: str = Field(min_length=10, max_length=64)
    status: str = Field(min_length=1, max_length=100)
    severity: Literal["info", "warning", "critical"] = "info"
    payload: dict[str, Any] = Field(default_factory=dict)


class InventoryRequest(AgentIdentity):
    collected_at: str = Field(min_length=10, max_length=64)
    os_name: str = Field(default="", max_length=255)
    os_version: str = Field(default="", max_length=255)
    cpu_name: str = Field(default="", max_length=500)
    cpu_cores: int = Field(default=0, ge=0, le=1024)
    ram_total_bytes: int = Field(default=0, ge=0)
    ram_used_bytes: int = Field(default=0, ge=0)
    primary_ipv4: str = Field(default="", max_length=45)
    manufacturer: str = Field(default="", max_length=255)
    model: str = Field(default="", max_length=255)
    bios_serial: str = Field(default="", max_length=255)
    system_uuid: str = Field(default="", max_length=128)
    baseboard_manufacturer: str = Field(default="", max_length=255)
    baseboard_product: str = Field(default="", max_length=255)
    baseboard_serial: str = Field(default="", max_length=255)
    disks: list[DiskInfo] = Field(default_factory=list, max_length=128)
    network: list[NetworkInfo] = Field(default_factory=list, max_length=128)
    software: list[SoftwareInfo] = Field(default_factory=list, max_length=20_000)
    completed_campaign_ids: list[int] = Field(default_factory=list, max_length=100)
    observations: list[MonitorObservation] = Field(default_factory=list, max_length=100)


class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=10, max_length=512)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=512)


class AssetPatch(BaseModel):
    display_name: str = Field(default="", max_length=200)
    asset_tag: str = Field(default="", max_length=100)
    department: str = Field(default="", max_length=200)


class AssetRetireRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


class AssetDeleteRequest(BaseModel):
    admin_password: str = Field(min_length=1, max_length=512)
    confirmation: str = Field(min_length=1, max_length=20)


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class DepartmentState(BaseModel):
    enabled: bool


class DepartmentRename(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class WallpaperExclusionCreate(BaseModel):
    asset_id: int = Field(ge=1)
    reason: str = Field(default="", max_length=500)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=10, max_length=512)
    role: Literal["admin", "viewer"]


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=3, max_length=100)


class ApiKeyState(BaseModel):
    enabled: bool


class PolicyUpdate(BaseModel):
    scope_type: Literal["global", "department"]
    scope_value: str = Field(default="", max_length=200)
    heartbeat_seconds: int = Field(default=120, ge=30, le=3600)
    online_threshold_seconds: int = Field(default=300, ge=60, le=86400)
    boot_delay_seconds: int = Field(default=600, ge=0, le=86400)
    daily_enabled: bool = False
    daily_time: str = Field(default="02:00", min_length=5, max_length=5)


class CampaignCreate(BaseModel):
    target_type: Literal["all", "department", "asset"]
    target_value: str = Field(default="", max_length=200)


class AgentRolloutCreate(BaseModel):
    release_id: int = Field(ge=1)
    target_type: Literal["all", "department", "asset"]
    target_value: str = Field(default="", max_length=200)
    admin_password: str = Field(min_length=1, max_length=512)
    confirmation: str = Field(min_length=1, max_length=32)


class UpdateConfigRequest(BaseModel):
    enabled: bool = False
    backup_retention: int = Field(default=5, ge=1, le=20)
    admin_password: str = Field(min_length=1, max_length=512)


class UpdateRollbackRequest(BaseModel):
    update_id: int = Field(ge=1)
    admin_password: str = Field(min_length=1, max_length=512)
    confirmation: str = Field(min_length=1, max_length=20)
