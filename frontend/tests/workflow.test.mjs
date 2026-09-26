import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runWorkflow } from '../src/lib/workflow.ts';

const drift = { environmental_asset_id: 'env', latitude: 20, longitude: 70, observed_at: '2026-09-20T12:00:00Z', duration_hours: 24 };
const ranking = { ais_asset_id: 'ais', search_radius_km: 25 };
const backward = { trajectory: { features: [{ geometry: { type: 'Point', coordinates: [69, 19] }, properties: { timestamp: '2026-09-19T12:00:00Z' } }] } };
const hooks = { backward() {}, forward() {}, attribution() {} };

test('sequential workflow ranks the newly returned origin and preserves observation for forecast', async () => {
  const calls = [];
  const stages = [];
  await runWorkflow({
    async driftBackward(payload) { calls.push('backward'); assert.deepEqual(payload, drift); return backward; },
    async driftForward(payload) { calls.push('forward'); assert.deepEqual(payload, { ...drift, duration_hours: 48 }); return {}; },
    async rankSuspects(payload) {
      calls.push('rank');
      assert.deepEqual(payload, { ...ranking, origin_latitude: 19, origin_longitude: 69, estimated_origin_at: '2026-09-19T12:00:00Z', use_hindcast_region: true });
      return { candidate_count: 0, candidates: [] };
    },
  }, drift, 48, ranking, stage => stages.push(stage), hooks);
  assert.deepEqual(calls, ['backward', 'forward', 'rank']);
  assert.deepEqual(stages, ['hindcast', 'forecast', 'ranking']);
});

test('forecast failure preserves hindcast callback and never starts ranking', async () => {
  let saved = false;
  await assert.rejects(runWorkflow({
    async driftBackward() { return backward; },
    async driftForward() { throw new Error('coverage missing'); },
    async rankSuspects() { assert.fail('ranking must not run'); },
  }, drift, 48, ranking, () => {}, { ...hooks, backward() { saved = true; } }), /coverage missing/);
  assert.equal(saved, true);
});

test('missing hindcast origin stops dependent stages', async () => {
  await assert.rejects(runWorkflow({
    async driftBackward() { return { trajectory: { features: [] } }; },
    async driftForward() { assert.fail('forecast must not run'); },
    async rankSuspects() { assert.fail('ranking must not run'); },
  }, drift, 48, ranking, () => {}, hooks), /no usable origin/);
});
