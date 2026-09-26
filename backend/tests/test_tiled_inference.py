import numpy as np
import pytest
import torch
from fastapi import HTTPException
from app.core.config import Settings
from app.ml.inference import SegmentationRunner
from app.geospatial.satellite import segment_satellite, _check_dimensions

class Pointwise(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.sizes=[]
    def forward(self, tensor):
        self.sizes.append(tuple(tensor.shape))
        return tensor[:, :1] * 2 - 1

@pytest.mark.parametrize('height,width', [(1,1),(7,13),(256,256),(273,531),(511,257)])
def test_weighted_tiles_cover_edges_and_match_pointwise_reference(monkeypatch,height,width):
    image=np.random.default_rng(7).normal(size=(3,height,width)).astype('float32')
    model=Pointwise()
    runner=SegmentationRunner(Settings())
    monkeypatch.setattr(runner,'_load_model',lambda:model)
    reads=[]
    def read(y,x,h,w):
        reads.append((h,w))
        return image[:,y:y+h,x:x+w]
    result=runner.predict_windows(read,height,width,image)
    lo,hi=np.percentile(image[0],(2,98))
    if hi<=lo: hi=lo+1
    normalized=np.clip((image[0]-lo)/(hi-lo),0,1)
    expected=1/(1+np.exp(-(normalized*2-1)))
    np.testing.assert_allclose(result,expected,atol=2e-7)
    assert result.shape==(height,width)
    assert max(max(size) for size in reads)<=256
    assert all(s[-1]<=256 and s[-2]<=256 for s in model.sizes)


def test_nodata_is_not_classified(monkeypatch):
    image=np.ones((3,280,300),dtype='float32')
    image[:,50:100,40:80]=np.nan
    runner=SegmentationRunner(Settings())
    monkeypatch.setattr(runner,'_load_model',lambda:Pointwise())
    result=runner.predict(image)
    assert np.all(result[50:100,40:80]==0)
    assert np.isfinite(result).all()
    assert result[0,0]>0


def test_limits_reject_before_model_loading(monkeypatch):
    runner=SegmentationRunner(Settings())
    monkeypatch.setattr(runner,'_load_model',lambda:pytest.fail('Model should not load'))
    with pytest.raises(HTTPException):
        runner.predict_windows(None,5000,5000,np.ones((3,1,1)))
    with pytest.raises(HTTPException):
        _check_dimensions(3000,3000,png=True)


def test_integer_geotiff_nodata_and_geographic_polygon(monkeypatch,tmp_path):
    import rasterio
    from rasterio.transform import from_origin
    path=tmp_path/'scene.tif'
    pixels=np.full((1,273,301),100,dtype='uint16')
    pixels[:,0:25,:]=0
    with rasterio.open(path,'w',driver='GTiff',width=301,height=273,count=1,dtype='uint16',nodata=0,crs='EPSG:4326',transform=from_origin(70,20,.001,.001)) as dst:
        dst.write(pixels)
    real_open = rasterio.open
    reads = []
    class WindowedDataset:
        def __init__(self, dataset): self.dataset = dataset
        def __enter__(self): return self
        def __exit__(self, *args): self.dataset.close()
        def __getattr__(self, name): return getattr(self.dataset, name)
        def read(self, *args, **kwargs):
            assert "window" in kwargs or "out_shape" in kwargs
            reads.append(kwargs)
            return self.dataset.read(*args, **kwargs)
    monkeypatch.setattr(rasterio, 'open', lambda *args, **kwargs: WindowedDataset(real_open(*args, **kwargs)))
    monkeypatch.setattr(SegmentationRunner,'assert_ready',lambda self:None)
    monkeypatch.setattr(SegmentationRunner,'_load_model',lambda self:Pointwise())
    monkeypatch.setattr(SegmentationRunner,'model_metadata',lambda self:{'test_fixture':True})
    features,_,metadata=segment_satellite(path,settings=Settings(),threshold=.2,bounds=None)
    assert len(reads) > 2
    assert metadata['positive_pixel_count']==248*301
    assert metadata['inference']['tile_size']==256
    assert len(features['features'])==1
    from shapely.geometry import shape
    assert shape(features['features'][0]['geometry']).bounds==pytest.approx((70,19.727,70.301,19.975))
