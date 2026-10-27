"""
KeyManager — Multi-source credential resolution.

Priority: File (.env/.json) > Environment Variables > OS Keyring

API Key env vars:     THEPROTOCOL_KEY_<SERVICE_ID>
OAuth env vars:       THEPROTOCOL_OAUTH_<SERVICE_ID>_CLIENT_ID / _CLIENT_SECRET

A name=value key file (a file named ``.env`` or ending in ``.env``) takes the same names as the environment. An OAuth
pair comes whole from one source: the file's, else the environment's, else the keyring's.
"""

import json
import logging
import os
import pathlib
from typing import Dict, Optional, Union

from dotenv import dotenv_values

from ..exceptions import KeyManagementError

logger = logging.getLogger(__name__)

try:
    import keyring
    _keyring_available = True
except ImportError:
    keyring = None  # type: ignore
    _keyring_available = False


class KeyManager:
    """Load and retrieve API keys and OAuth credentials from files, env vars, or OS keyring."""

    def __init__(
        self,
        key_file_path: Optional[Union[str, pathlib.Path]] = None,
        use_env_vars: bool = True,
        use_keyring: bool = False,
        env_prefix: str = "THEPROTOCOL_KEY_",
        oauth_env_prefix: str = "THEPROTOCOL_OAUTH_",
    ):
        self.key_file_path = pathlib.Path(key_file_path).resolve() if key_file_path else None
        self.use_env_vars = use_env_vars
        self.env_prefix = env_prefix
        self.oauth_env_prefix = oauth_env_prefix
        self._keys: Dict[str, str] = {}
        self._key_sources: Dict[str, str] = {}
        self._oauth_creds: Dict[str, Dict[str, str]] = {}
        self._oauth_sources: Dict[str, str] = {}

        self.use_keyring = False
        if use_keyring and _keyring_available:
            try:
                keyring.get_keyring()  # type: ignore
                self.use_keyring = True
            except Exception:
                pass

        self._load()

    def _load(self):
        self._keys.clear()
        self._key_sources.clear()
        self._oauth_creds.clear()
        self._oauth_sources.clear()
        if self.key_file_path:
            self._load_file()
        if self.use_env_vars:
            self._load_env()

    def _load_file(self):
        if not self.key_file_path or not self.key_file_path.exists():
            return
        ext = self.key_file_path.suffix.lower()
        # pathlib gives a file named exactly ".env" no suffix at all, so that name is matched on its own
        if self.key_file_path.name.lower() == ".env":
            ext = ".env"
        try:
            if ext == ".env":
                for k, v in dotenv_values(self.key_file_path).items():
                    if not v:
                        continue
                    if k.startswith(self.oauth_env_prefix):
                        self._parse_oauth_env_key(k, v, 'file')
                    else:
                        # THEPROTOCOL_KEY_<SERVICE_ID> is the key of <service id>, as in the environment; any other
                        # name is kept under its own name
                        nid = (k[len(self.env_prefix):] if k.startswith(self.env_prefix) else k).lower()
                        if nid:
                            self._keys[nid] = v
                            self._key_sources[nid] = 'file'
            elif ext == ".json":
                data = json.loads(self.key_file_path.read_text())
                if not isinstance(data, dict):
                    return
                for k, v in data.items():
                    nid = k.lower()
                    if isinstance(v, str) and v:
                        self._keys[nid] = v
                        self._key_sources[nid] = 'file'
                    elif isinstance(v, dict):
                        if isinstance(v.get("apiKey"), str) and v["apiKey"]:
                            self._keys[nid] = v["apiKey"]
                            self._key_sources[nid] = 'file'
                        if isinstance(v.get("oauth"), dict):
                            oauth = v["oauth"]
                            cid = oauth.get("clientId", "")
                            csec = oauth.get("clientSecret", "")
                            if cid or csec:
                                self._oauth_creds[nid] = {}
                                if cid:
                                    self._oauth_creds[nid]["clientId"] = cid
                                if csec:
                                    self._oauth_creds[nid]["clientSecret"] = csec
                                self._oauth_sources[nid] = 'file'
            else:
                logger.warning(f"Key file {self.key_file_path} is neither a .env nor a .json file; it was not read")
        except Exception as e:
            logger.error(f"Error loading key file {self.key_file_path}: {e}")

    def _parse_oauth_env_key(self, key: str, value: str, source: str):
        remaining = key[len(self.oauth_env_prefix):]
        if remaining.endswith("_CLIENT_ID"):
            nid = remaining[:-len("_CLIENT_ID")].lower()
            cred_type = "clientId"
        elif remaining.endswith("_CLIENT_SECRET"):
            nid = remaining[:-len("_CLIENT_SECRET")].lower()
            cred_type = "clientSecret"
        else:
            return
        if source != 'file' and self._oauth_sources.get(nid) == 'file':
            return  # File has priority (the file's own second line still belongs to the pair)
        if nid not in self._oauth_creds:
            self._oauth_creds[nid] = {}
        self._oauth_creds[nid][cred_type] = value
        self._oauth_sources[nid] = source

    def _load_env(self):
        for var, val in os.environ.items():
            if var.startswith(self.env_prefix):
                nid = var[len(self.env_prefix):].lower()
                if nid and val and nid not in self._key_sources:
                    self._keys[nid] = val
                    self._key_sources[nid] = 'env'
            elif var.startswith(self.oauth_env_prefix):
                self._parse_oauth_env_key(var, val, 'env')

    def get_key(self, service_id: str) -> Optional[str]:
        """Get API key for a service."""
        nid = service_id.lower()
        if nid in self._keys:
            return self._keys[nid]
        if self.use_keyring and _keyring_available:
            try:
                val = keyring.get_password(f"theprotocol:{nid}", nid)  # type: ignore
                if val:
                    self._keys[nid] = val
                    self._key_sources[nid] = 'keyring'
                    return val
            except Exception:
                pass
        return None

    def get_oauth_client_id(self, service_id: str) -> Optional[str]:
        """Get OAuth client ID for a service."""
        nid = service_id.lower()
        creds = self._oauth_creds.get(nid, {})
        if "clientId" in creds:
            return creds["clientId"]
        if self.use_keyring and _keyring_available and nid not in self._oauth_sources:
            self._load_oauth_keyring(nid)
            return self._oauth_creds.get(nid, {}).get("clientId")
        return None

    def get_oauth_client_secret(self, service_id: str) -> Optional[str]:
        """Get OAuth client secret for a service."""
        nid = service_id.lower()
        creds = self._oauth_creds.get(nid, {})
        if "clientSecret" in creds:
            return creds["clientSecret"]
        if self.use_keyring and _keyring_available and nid not in self._oauth_sources:
            self._load_oauth_keyring(nid)
            return self._oauth_creds.get(nid, {}).get("clientSecret")
        return None

    def _load_oauth_keyring(self, nid: str):
        if not _keyring_available:
            return
        try:
            cid = keyring.get_password(f"theprotocol:oauth:{nid}", "clientId")  # type: ignore
            csec = keyring.get_password(f"theprotocol:oauth:{nid}", "clientSecret")  # type: ignore
            if cid and csec:
                self._oauth_creds[nid] = {"clientId": cid, "clientSecret": csec}
                self._oauth_sources[nid] = 'keyring'
        except Exception:
            pass
