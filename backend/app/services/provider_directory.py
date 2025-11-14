import requests
from typing import List, Dict, Optional

NPPES_URL = "https://npiregistry.cms.hhs.gov/api/"

def _nppes_get(params: Dict) -> Dict:
    params = {"version": "2.1", **params}
    r = requests.get(NPPES_URL, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def search_providers(*, city: Optional[str]=None, state: Optional[str]=None, postal_code: Optional[str]=None, organization_name: Optional[str]=None, first_name: Optional[str]=None, last_name: Optional[str]=None, limit:int=25) -> List[Dict]:
    params = {"limit": limit}
    if city:
        params["city"] = city
    if state:
        params["state"] = state
    if postal_code:
        params["postal_code"] = postal_code
    if organization_name:
        params["organization_name"] = organization_name
    if first_name:
        params["first_name"] = first_name
    if last_name:
        params["last_name"] = last_name

    try:
        data = _nppes_get(params)
    except Exception:
        return []

    out = []
    for res in data.get("results", []):
        addresses = res.get("addresses", [])
        location = next((a for a in addresses if a.get("address_purpose") == "LOCATION"), {}) if addresses else {}
        fax = location.get("fax_number") or None
        phone = location.get("telephone_number") or None
        city_val = location.get("city")
        state_val = location.get("state")
        postal = location.get("postal_code")
        name = None
        if res.get("basic", {}).get("organization_name"):
            name = res["basic"]["organization_name"]
        else:
            first = res.get("basic", {}).get("first_name") or ""
            last = res.get("basic", {}).get("last_name") or ""
            name = (first + " " + last).strip()
        npi = res.get("number")
        out.append({
            "npi": str(npi) if npi else None,
            "name": name,
            "type": (res.get("enumeration_type") or ""),
            "address_line1": location.get("address_1"),
            "address_line2": location.get("address_2"),
            "city": city_val,
            "state": state_val,
            "postal_code": postal[:5] if postal else None,
            "phone": phone,
            "fax": fax,
            "source": "nppes"
        })
    return out