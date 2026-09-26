import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException
from pyproj import Geod
from app.drift.advection import EnvironmentalField, simulate_particles

def observations(rows):
    frame=pd.DataFrame(rows,columns=['timestamp','latitude','longitude','current_u','current_v','wind_u','wind_v'])
    frame.timestamp=pd.to_datetime(frame.timestamp,utc=True)
    return frame

T='2020-01-01T00:00:00Z'
T1='2020-01-01T01:00:00Z'

def test_spatial_and_temporal_interpolation_and_exact_samples():
    field=EnvironmentalField(observations([[T,0,-.01,0,0,0,0],[T,0,.01,2,0,0,0],[T1,0,-.01,2,0,0,0],[T1,0,.01,4,0,0,0]]))
    value=field.velocity(pd.Timestamp('2020-01-01T00:30:00Z'),np.array([0.,0.,0.]),np.array([-.01,0,.01]))
    np.testing.assert_allclose(value[:,0],[1,2,3],atol=1e-8)

def run(frame,duration=.75,direction=1,start=T,spread=0):
    return simulate_particles(frame,latitude=0,longitude=0,observed_at=start,duration_hours=duration,step_minutes=30,particle_count=20,initial_spread_meters=spread,windage_factor=0,direction=direction,random_seed=42)

def test_constant_current_exact_duration_and_reverse():
    frame=observations([[T,0,0,1,0,0,0],[T1,0,0,1,0,0,0]])
    result=run(frame)
    features=result['trajectory']['features']
    assert len(features)==3
    assert pd.Timestamp(features[-1]['properties']['timestamp'])==pd.Timestamp('2020-01-01T00:45:00Z')
    lon,lat=features[-1]['geometry']['coordinates']
    distance=Geod(ellps='WGS84').inv(0,0,lon,lat)[2]
    assert distance==pytest.approx(2700,abs=.01)
    reverse=run(frame,direction=-1,start=T1)
    assert reverse['trajectory']['features'][-1]['geometry']['coordinates'][0]<0

def test_time_varying_current_integrated_at_midpoints():
    frame=observations([[T,0,0,0,0,0,0],[T1,0,0,2,0,0,0]])
    result=run(frame,duration=1)
    lon,lat=result['trajectory']['features'][-1]['geometry']['coordinates']
    assert Geod(ellps='WGS84').inv(0,0,lon,lat)[2]==pytest.approx(3600,abs=.01)

def test_gaps_are_not_silently_accepted():
    field=EnvironmentalField(observations([[T,0,0,1,0,0,0]]))
    field.velocity(pd.Timestamp(T1),np.array([0.]),np.array([0.]))
    assert any('held constant' in warning for warning in field.warnings)
    with pytest.raises(HTTPException):
        field.velocity(pd.Timestamp('2020-01-01T07:00:00Z'),np.array([0.]),np.array([0.]))
    with pytest.raises(HTTPException):
        field.velocity(pd.Timestamp(T),np.array([10.]),np.array([10.]))
    wide=EnvironmentalField(observations([[T,0,0,1,0,0,0],['2020-01-01T12:00:00Z',0,0,1,0,0,0]]))
    with pytest.raises(HTTPException):
        wide.velocity(pd.Timestamp(T1),np.array([0.]),np.array([0.]))

def test_deterministic_particle_seeding():
    frame=observations([[T,0,0,1,0,0,0],[T1,0,0,1,0,0,0]])
    assert run(frame,spread=250)==run(frame,spread=250)
