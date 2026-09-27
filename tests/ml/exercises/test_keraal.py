"""Fabricated geometry tests only, never dataset evaluation."""
import json
import unittest
from dataclasses import replace
from pathlib import Path

from processing.analysis.exercises.keraal import (
    SCHEMA,
    UPSTREAM_REVISION,
    Annotation,
    Frame,
    Sequence,
    elk_features,
    evaluate,
    fit,
    ingest_blazepose,
    parse_annotations,
    partition,
    predict,
)


def sequence(participant='person-a', take='take-a', raised=False):
    joints = {'Left_shoulder': (0., 0.), 'Right_shoulder': (2., 0.),
              'Left_hip': (0., 2.), 'Right_hip': (2., 2.),
              'Left_elbow': (0., 1.), 'Right_elbow': (2., 1.),
              'Left_wrist': (0., 2.), 'Right_wrist': (2., 2.)}
    if raised:
        joints['Left_wrist'] = (-2., 0.)
        joints['Left_elbow'] = (-1., 0.)
    return Sequence(participant, take, 'elk', 'fixture-tracker',
                    (Frame(4, 0., joints), Frame(9, .17, joints)), (),
                    view='front', capture_complete=True)


def labelled(participant, take, label, raised=False):
    s = sequence(participant, take, raised)
    return replace(s, annotations=(Annotation('reviewer-a', 'Global evaluation',
        0., .17, {'evaluation': 'Correct' if label == 0 else 'Incorrect'}),
        Annotation('reviewer-a', 'Global error', 0., .17,
                   {'type': 'none' if label == 0 else 'Error1'})))


def anvil(track='Global evaluation', attrs='<attribute name="evaluation">Correct</attribute>'):
    return f'<annotation><body><track name="{track}"><el index="0" start="0" end="0.17">{attrs}</el></track></body></annotation>'.encode()


class AnnotationTests(unittest.TestCase):
    def test_tracks_and_annotators_retained(self):
        rows = parse_annotations(anvil('Temporal error', '<attribute name="type">Error1</attribute><attribute name="bodyPart">LeftArm</attribute>'), 'doctor')
        self.assertEqual(rows[0].track, 'Temporal error')
        self.assertEqual(rows[0].annotator, 'doctor')
        self.assertEqual(rows[0].attributes['bodyPart'], 'LeftArm')
        self.assertEqual(rows[0].end_s, .17)

    def test_global_is_not_temporal(self):
        self.assertEqual(parse_annotations(anvil(), 'doctor')[0].track, 'Global evaluation')
        protocol = json.loads((Path(__file__).resolve().parents[3] /
            'processing/analysis/exercises/protocol.json').read_text())
        self.assertEqual(protocol['upstream']['revision'], UPSTREAM_REVISION)
        self.assertEqual(protocol['annotation']['global_error'], 'worst_error_over_sequence')
        self.assertEqual(protocol['annotation']['temporal_error'], 'explicit_start_end_only')
        for exercise in ('elk', 'rtk'):
            self.assertEqual(set(protocol['exercises'][exercise]['labels']),
                             SCHEMA['Temporal error']['type'] - {'Other'})
        self.assertEqual(protocol['verification']['live_support'], 'unsupported')

    def test_reject_hostile_or_unknown_annotations(self):
        bad = [b'<!DOCTYPE a><annotation/>', b'<broken', anvil('unknown'),
               anvil(attrs='<attribute name="evaluation">Excellent</attribute>'),
               anvil().replace(b'end="0.17"', b'end="-1"'),
               anvil().replace(b'start="0"', b'start="nan"'),
               anvil(attrs='<attribute name="evaluation">Correct</attribute>' * 2)]
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_annotations(raw, 'doctor')


class IngestionTests(unittest.TestCase):
    def payload(self):
        s = sequence()
        positions = {str(i): {k: [x / 100, y / 50, 0.] for k, (x, y) in f.joints.items()}
                     for i, f in enumerate(s.frames, 1)}
        mapping = {str(i): {'frame_id': f.frame_id, 'time_s': f.time_s,
                           'valid_joints': list(f.joints)} for i, f in enumerate(s.frames, 1)}
        return json.dumps({'positions': positions}).encode(), mapping

    def ingest(self, raw, mapping, **kwargs):
        return ingest_blazepose(raw, participant_id='person-a', take_id='take-a',
            exercise='elk', tracker_version='fixture-tracker', width=100, height=50,
            source_map=mapping, mapping_provenance=kwargs.get('provenance', 'verified-fixture'),
            anatomical_sides_verified=kwargs.get('sides', True),
            view='front', capture_complete=True)

    def test_preserves_source_frames_and_aspect_ratio(self):
        raw, mapping = self.payload()
        s = self.ingest(raw, mapping)
        self.assertEqual([f.frame_id for f in s.frames], [4, 9])
        self.assertEqual(s.frames[1].time_s, .17)
        self.assertEqual(elk_features(s), elk_features(sequence()))

    def test_missing_is_invalid_not_zero(self):
        raw, mapping = self.payload()
        mapping['1']['valid_joints'].remove('Left_wrist')
        s = self.ingest(raw, mapping)
        self.assertIsNone(s.frames[0].joints['Left_wrist'])
        with self.assertRaises(ValueError):
            elk_features(s)

    def test_reject_unverified_or_bad_maps(self):
        raw, mapping = self.payload()
        for kwargs in ({'provenance': ''}, {'sides': False}):
            with self.assertRaises(ValueError):
                self.ingest(raw, mapping, **kwargs)
        for altered in ({}, {'1': mapping['1']}, {**mapping, '2': mapping['1']}):
            with self.assertRaises(ValueError):
                self.ingest(raw, altered)

    def test_reject_malformed_landmarks_and_metadata(self):
        raw, mapping = self.payload()
        for value in ([0, 0], [0, float('inf'), 0], [True, 0, 0]):
            data = json.loads(raw)
            data['positions']['1']['Left_wrist'] = value
            with self.assertRaises(ValueError):
                self.ingest(json.dumps(data).encode(), mapping)
        for change in ({'frame_id': True}, {'time_s': -1}, {'valid_joints': ['unknown']},
                       {'valid_joints': ['Left_wrist', 'Left_wrist']}):
            altered = {**mapping, '1': {**mapping['1'], **change}}
            with self.assertRaises(ValueError):
                self.ingest(raw, altered)

    def test_reject_bad_json(self):
        _, mapping = self.payload()
        for raw in (b'{"positions":{},"positions":{}}', b'{"positions":NaN}', b'[]'):
            with self.assertRaises(ValueError):
                self.ingest(raw, mapping)


class FeatureTests(unittest.TestCase):
    def test_translation_scale_invariance(self):
        s = sequence()
        moved = replace(s, frames=tuple(replace(f, joints={k: (x*3+10, y*3-2)
            for k, (x,y) in f.joints.items()}) for f in s.frames))
        self.assertEqual(elk_features(s), elk_features(moved))

    def test_reject_rtk_degenerate_and_irregular_invalid_frames(self):
        s = sequence()
        bad = [replace(s, exercise='rtk'), replace(s, frames=()),
               replace(s, view='left'), replace(s, capture_complete=False),
               replace(s, frames=(s.frames[1], s.frames[0])),
               replace(s, frames=(replace(s.frames[0], joints={k:(0.,0.) for k in s.frames[0].joints}),))]
        for row in bad:
            with self.assertRaises(ValueError):
                elk_features(row)


class EvaluationTests(unittest.TestCase):
    def training(self):
        return [labelled('a', 'a0', 0), labelled('a', 'a1', 1, True),
                labelled('b', 'b0', 0), labelled('b', 'b1', 1, True)]

    def test_participant_first_and_complete_split(self):
        rows = self.training()
        train, test = partition(rows, {'a'}, {'b'})
        self.assertEqual({s.participant_id for s in train}, {'a'})
        self.assertEqual({s.participant_id for s in test}, {'b'})
        for ids in (({'a'}, {'a','b'}), ({'a'}, {'c'})):
            with self.assertRaises(ValueError):
                partition(rows, *ids)

    def test_train_only_normalization_and_no_test_leakage(self):
        model = fit(self.training(), annotator='reviewer-a')
        before = model
        result = evaluate(model, [labelled('c', 'c0', 0)], annotator='reviewer-a')
        self.assertEqual(result['counts'], {'tn': 1, 'fp': 0, 'fn': 0, 'tp': 0})
        self.assertIsNone(result['recall_error1'])
        self.assertEqual(model, before)
        with self.assertRaises(ValueError):
            evaluate(model, [labelled('a', 'new-take', 0)], annotator='reviewer-a')

    def test_requires_both_classes_and_explicit_review(self):
        for rows in ([], [labelled('a','a0',0)], [sequence()]):
            with self.assertRaises(ValueError):
                fit(rows, annotator='reviewer-a')
        with self.assertRaises(ValueError):
            fit(self.training(), annotator='other')

    def test_evidence_is_clip_prediction_not_temporal_ground_truth(self):
        model = fit(self.training(), annotator='reviewer-a')
        result = predict(model, sequence('c', 'take-c', True))
        self.assertEqual(result['take_id'], 'take-c')
        self.assertEqual(result['source_frame_ids'], [4, 9])
        self.assertEqual(result['granularity'], 'clip')
        self.assertNotIn('confidence', result)
        self.assertEqual(result['label_code'], 'elk.Error1')

    def test_global_correct_cannot_contradict_temporal_error(self):
        rows = self.training()
        contradictory = replace(rows[0], annotations=rows[0].annotations + (
            Annotation('reviewer-a', 'Temporal error', 0., .17, {'type':'Error1'}),))
        with self.assertRaises(ValueError):
            fit([contradictory, rows[1]], annotator='reviewer-a')

    def test_ambiguous_model_abstains(self):
        model = fit([labelled('a','a0',0), labelled('b','b1',1)], annotator='reviewer-a')
        with self.assertRaises(ValueError):
            predict(model, sequence())

    def test_all_confusion_counts_and_take_isolation(self):
        model = fit(self.training(), annotator='reviewer-a')
        heldout = [labelled('c','c0',0), labelled('c','c1',0,True),
                   labelled('d','d0',1), labelled('d','d1',1,True)]
        result = evaluate(model, heldout, annotator='reviewer-a')
        self.assertEqual(result['counts'], {'tn': 1,'fp': 1,'fn': 1,'tp': 1})
        self.assertEqual(result['precision_error1'], .5)
        self.assertEqual(result['precision_correct'], .5)
        with self.assertRaises(ValueError):
            evaluate(model, [labelled('unseen', 'a0', 0)], annotator='reviewer-a')

    def test_reject_tracker_mismatch_other_errors_and_duplicate_takes(self):
        rows = self.training()
        model = fit(rows, annotator='reviewer-a')
        with self.assertRaises(ValueError):
            predict(model, replace(sequence(), tracker_version='different'))
        with self.assertRaises(ValueError):
            fit(rows + [rows[0]], annotator='reviewer-a')
        bad = replace(rows[1], annotations=(rows[1].annotations[0],
            replace(rows[1].annotations[1], attributes={'type':'Error2'})))
        with self.assertRaises(ValueError):
            fit([rows[0], bad], annotator='reviewer-a')


if __name__ == '__main__':
    unittest.main()
