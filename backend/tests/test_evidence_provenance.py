import io
import json
import zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import get_settings

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('SEASCAN_DATABASE_URL', f'sqlite:///{tmp_path}/provenance.db')
    monkeypatch.setenv('SEASCAN_UPLOAD_DIRECTORY', str(tmp_path/'uploads'))
    monkeypatch.setenv('SEASCAN_PROCESSED_DIRECTORY', str(tmp_path/'processed'))
    get_settings.cache_clear()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def upload(client, provenance=None):
    case=client.post('/api/investigations',json={'title':'Provenance regression'}).json()['id']
    data={'investigation_id':case}
    if provenance is not None: data['provenance']=json.dumps(provenance)
    response=client.post('/api/ais/upload',data=data,files={'file':('ais.csv',(Path(__file__).parent/'fixtures/ais.csv').read_bytes(),'text/csv')})
    return case,response


def test_provenance_survives_reopen_and_report_manifest(client):
    declared={'evidence_kind':'synthetic','source_organization':'Demo <team> & lab','source_reference':'internal controlled case','dataset_version':'v1','acquired_at':'2018-12-19T12:00:00Z','added_by':'Demo analyst','prior_processing':'Generated tracks','declared_crs':'EPSG:4326'}
    case,response=upload(client,declared)
    assert response.status_code==201,response.text
    asset=response.json()['asset']
    assert asset['metadata']['provenance']==declared
    assert len(asset['sha256'])==64
    restored=client.get(f'/api/investigations/{case}').json()['assets'][0]
    assert restored['metadata']==asset['metadata']
    result=client.post('/api/reports/package.zip',json={'investigation_id':case})
    assert result.status_code==200
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        manifest=json.loads(archive.read('manifest.json'))
    assert manifest['schema_version']=='1.1'
    assert manifest['evidence_assets'][0]['provenance']==declared
    assert manifest['evidence_assets'][0]['processing_steps']


def test_missing_provenance_does_not_claim_real_data(client):
    _,response=upload(client)
    assert response.status_code==201
    assert response.json()['asset']['metadata']['provenance']['evidence_kind']=='unknown'


@pytest.mark.parametrize('declaration',[
    {'evidence_kind':'verified'}, {'acquired_at':'2018-12-19T12:00:00'},
    {'source_organization':'x'*201}, {'weights_sha256':'forged'},
])
def test_invalid_or_server_owned_provenance_rejected(client,declaration):
    _,response=upload(client,declaration)
    assert response.status_code==422
