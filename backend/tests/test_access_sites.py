"""The Master saves a person's rights and assigned sites together from the Access tab."""
from test_department_members import person


def test_access_save_also_sets_sites(tenant):
    emp = person(tenant, "Sited")
    job = tenant.post("/api/jobs", json={"name": "Bypass"}).json()
    job_id = job.get("id") or job.get("job", {}).get("id")
    res = tenant.put(f"/api/employees/{emp}/permissions", json={"permission_role": "staff", "permissions": ["self.service"], "site_ids": [job_id]})
    assert res.status_code == 200
    detail = tenant.get(f"/api/employees/{emp}").json()
    assert detail["site_ids"] == [job_id] and not detail["all_sites"]
    tenant.put(f"/api/employees/{emp}/permissions", json={"permission_role": "staff", "permissions": ["self.service"], "site_ids": []})
    assert tenant.get(f"/api/employees/{emp}").json()["all_sites"] is True


def test_access_save_without_sites_leaves_them(tenant):
    emp = person(tenant, "Keeps")
    job = tenant.post("/api/jobs", json={"name": "Keep"}).json()
    job_id = job.get("id") or job.get("job", {}).get("id")
    tenant.put(f"/api/employees/{emp}/permissions", json={"permission_role": "staff", "site_ids": [job_id]})
    tenant.put(f"/api/employees/{emp}/permissions", json={"permission_role": "staff"})
    assert tenant.get(f"/api/employees/{emp}").json()["site_ids"] == [job_id]
