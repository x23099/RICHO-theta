"""Real PNG, bounded malformed packets and deterministic local deadline tests."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch
import zlib

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
import driver_lossless_frame_packet as png
import driver_lossless_frame_fragments as flow
import driver_frame_packet as vp8
from test_driver_frame_packet import candidate, SENDER, STREAM


def receiver():
    return png.LosslessPacketReceiver(sender_id=SENDER, stream_id=STREAM)


def assembler():
    return flow.LosslessReassembler(sender_id=SENDER, stream_id=STREAM)


def clock(*values):
    return iter(values).__next__


def chunk(kind, body):
    return struct.pack('!I',len(body))+kind+body+struct.pack('!I',zlib.crc32(kind+body)&0xffffffff)


class LosslessPacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Structured image compresses below cap but requires multiple fragments.
        cls.image = np.random.default_rng(19).integers(0,64,(720,1280,3),dtype=np.uint8)
        cls.image[:] = cls.image // 8 * 32
        cls.meta = candidate(v=-.2,w=.1)
        cls.wire = png.encode_packet(cls.image,cls.meta)
        cls.header, cls.payload = png.unpack_packet(cls.wire)
        cls.parts = list(flow.fragments(cls.wire))
        assert len(cls.parts)>2

    def test_exact_pixels_candidate_readonly_and_no_source_mutation(self):
        before = hashlib.sha256(self.image.tobytes()).hexdigest()
        meta = copy.deepcopy(self.meta)
        value, image = png.decode_packet(self.wire)
        self.assertEqual(value, meta)
        np.testing.assert_array_equal(image,self.image)
        self.assertFalse(image.flags.writeable)
        self.assertEqual(before,hashlib.sha256(self.image.tobytes()).hexdigest())
        self.assertEqual(self.meta,meta)
        self.assertTrue(all(value[k] is False for k in vp8.FLAGS))

    def test_withheld_motion_does_not_gain_old_velocity(self):
        value,image = png.decode_packet(png.encode_packet(self.image,candidate(withheld=True)))
        self.assertFalse(value['local_pair_available'])
        self.assertIsNone(value['odometry_observation'])
        np.testing.assert_array_equal(image,self.image)

    def test_not_interchangeable_with_vp8(self):
        with self.assertRaises(ValueError):vp8.unpack_packet(self.wire)
        with self.assertRaises(ValueError):png.unpack_packet(vp8.encode_packet(self.image,self.meta))

    def test_corruption_truncation_and_extra_bytes(self):
        for wire in (b'',self.wire[:-1],self.wire+b'x',self.wire[:100]+b'!'+self.wire[101:]):
            with self.subTest(size=len(wire)), self.assertRaises(ValueError):png.unpack_packet(wire)

    def test_exact_header_and_identity_and_authority(self):
        for key,value in (('codec','VP8_INTRA'),('width',True),('width',640),
                          ('encoded_pts',77),('encoded_pts',2**32),('bgr_sha256','z'*64),
                          ('unexpected',False)):
            header=copy.deepcopy(self.header);header[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                png.unpack_packet(png._wrap(header,self.payload))
        header=copy.deepcopy(self.header);header['candidate']['usable_for_ffb']=True
        with self.assertRaises(ValueError):png.unpack_packet(png._wrap(header,self.payload))

    def test_bound_pixel_digest_rejects_payload_swap(self):
        header=copy.deepcopy(self.header);header['bgr_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'pixels differ'):
            png.decode_packet(png._wrap(header,self.payload))

    def test_duplicate_and_nonfinite_json_rejected(self):
        raw=json.dumps(self.header,separators=(',',':')).encode()
        for data in (b'{"width":1280,'+raw[1:],raw.replace(b'"width":1280',b'"width":1e999')):
            wire=png.PREFIX.pack(png.MAGIC,len(data),len(self.payload),hashlib.sha256(data+self.payload).digest())+data+self.payload
            with self.assertRaises(ValueError):png.unpack_packet(wire)

    def test_size_and_native_shape_caps(self):
        for image in (self.image[:100],self.image.astype(np.float32)):
            with self.assertRaises(ValueError):png.encode_packet(image,self.meta)
        with self.assertRaises(ValueError):png.checked_png(b'x'*(png.MAX_PAYLOAD+1))
        noise=np.random.default_rng(2).integers(0,256,(720,1280,3),dtype=np.uint8)
        with self.assertRaises(ValueError):png.encode_packet(noise,self.meta)

    def test_png_crc_and_chunk_order_trailing_rejected_before_cv2(self):
        bad=[self.payload[:-1],self.payload+b'x',self.payload[:29]+b'xxxx'+self.payload[33:],
             self.payload[:33]+chunk(b'tEXt',b'hello')+self.payload[33:],
             self.payload[:33]+self.payload[:33][8:]+self.payload[33:]]
        with patch('cv2.imdecode',side_effect=AssertionError('must reject before decoder')):
            for payload in bad:
                with self.subTest(size=len(payload)), self.assertRaises(ValueError):
                    png.decode_packet(png._wrap(self.header,payload))

    def test_png_dimensions_and_bounded_deflate(self):
        ihdr=chunk(b'IHDR',struct.pack('!IIBBBBB',1280,720,8,2,0,0,0))
        signature=b'\x89PNG\r\n\x1a\n'
        for raw in (b'\x00'*(png.FILTERED_BYTES+1),b'\x00'*(png.FILTERED_BYTES-1),
                    b'\x05'+b'\x00'*(png.FILTERED_BYTES-1)):
            payload=signature+ihdr+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
            with self.assertRaises(ValueError):png.checked_png(payload)
        for dimensions in ((999999,720,8,2,0,0,0),(1280,720,8,6,0,0,0),(1280,720,8,2,0,0,1)):
            payload=signature+chunk(b'IHDR',struct.pack('!IIBBBBB',*dimensions))+self.payload[33:]
            with self.assertRaises(ValueError):png.checked_png(payload)
        for extra in (b'x',zlib.compress(b'extra')):
            payload=signature+ihdr+chunk(b'IDAT',zlib.compress(b'\0'*png.FILTERED_BYTES)+extra)+chunk(b'IEND',b'')
            with self.assertRaises(ValueError):png.checked_png(payload)

    def test_receiver_one_shot_and_clocks_not_cross_subtracted(self):
        rec=receiver()
        self.assertTrue(rec.accept(self.wire,first_received_at_sec=5000.,now=clock(5000.01,5000.02)))
        value=rec.take(5000.03)
        self.assertEqual(value.candidate,self.meta)
        self.assertEqual(value.deadline_sec,5000.2)
        self.assertIsNone(rec.take(5000.04))

    def test_decode_and_consumption_share_first_fragment_deadline(self):
        rec=receiver()
        self.assertFalse(rec.accept(self.wire,first_received_at_sec=0.,now=clock(.19,.201)))
        self.assertIsNone(rec.take(.202))
        with self.assertRaisesRegex(ValueError,'duplicate'):
            rec.accept(self.wire,first_received_at_sec=.21,now=clock(.22,.23))
        rec=receiver()
        self.assertTrue(rec.accept(self.wire,first_received_at_sec=0.,now=clock(.1,.15)))
        self.assertIsNone(rec.take(.201))

    def test_already_expired_not_decoded_and_future_first_rejected(self):
        for start,before in ((0.,.201),(1.,.9)):
            with patch.object(png,'decode_packet',side_effect=AssertionError('late decode')):
                self.assertFalse(receiver().accept(self.wire,first_received_at_sec=start,now=clock(before)))

    def test_failed_update_clears_previous_pair(self):
        rec=receiver();rec.accept(self.wire,first_received_at_sec=0.,now=clock(.01,.02))
        with self.assertRaises(ValueError):rec.accept(b'bad',first_received_at_sec=.03,now=clock(.04))
        self.assertIsNone(rec.take(.05))

    def test_receiver_foreign_scope_and_source_order(self):
        rec=receiver();rec.stream_id='c'*32
        with self.assertRaises(ValueError):rec.accept(self.wire,first_received_at_sec=0.,now=clock(.01,.02))
        rec=receiver();rec.accept(self.wire,first_received_at_sec=0.,now=clock(.01,.02));rec.take(.03)
        with self.assertRaises(ValueError):rec.accept(self.wire,first_received_at_sec=.04,now=clock(.05,.06))

    def test_newer_sequence_with_repeated_pts_rejected(self):
        meta=candidate(sequence=2);meta['sender_media_pts']=self.meta['sender_media_pts']
        wire=png.encode_packet(self.image,meta)
        rec=receiver();rec.accept(self.wire,first_received_at_sec=0.,now=clock(.01,.02))
        with self.assertRaises(ValueError):rec.accept(wire,first_received_at_sec=.03,now=clock(.04,.05))
        self.assertIsNone(rec.take(.06))

    def test_new_independent_frame_after_a_missing_sequence(self):
        wire=png.encode_packet(self.image,candidate(sequence=3,v=.3,w=-.1))
        rec=receiver();rec.accept(self.wire,first_received_at_sec=0.,now=clock(.01,.02))
        self.assertTrue(rec.accept(wire,first_received_at_sec=.03,now=clock(.04,.05)))
        value=rec.take(.06)
        self.assertEqual(value.candidate['capture_sequence'],3)
        self.assertEqual(value.candidate['odometry_observation']['linear_mps'],.3)

    def test_withheld_new_frame_cannot_inherit_last_motion(self):
        wire=png.encode_packet(self.image,candidate(sequence=2,withheld=True))
        rec=receiver();rec.accept(self.wire,first_received_at_sec=0.,now=clock(.01,.02))
        self.assertTrue(rec.accept(wire,first_received_at_sec=.03,now=clock(.04,.05)))
        value=rec.take(.06)
        self.assertIsNone(value.candidate['odometry_observation'])
        self.assertFalse(value.candidate['local_pair_available'])

    def test_clock_reversal_and_close_retire_receiver(self):
        for end in (-.1,float('nan')):
            rec=receiver();rec.accept(self.wire,first_received_at_sec=0.,now=clock(.01,.02))
            self.assertIsNone(rec.take(end));self.assertTrue(rec.closed)
        rec=receiver();rec.close()
        self.assertFalse(rec.accept(self.wire,first_received_at_sec=0.,now=clock(.01)))

    def test_fragment_roundtrip_out_of_order_and_cap(self):
        rec=assembler();result=None
        for part in reversed(self.parts):result=rec.accept(part,100.)
        self.assertEqual(result.wire,self.wire)
        self.assertEqual(result.first_received_at_sec,100.)
        self.assertEqual(result.deadline_sec,100.2)
        self.assertLessEqual(max(map(len,self.parts)),16384)
        self.assertLessEqual(rec.peak_retained_bytes,png.MAX_PACKET)
        self.assertIsNone(rec.active)
        for part in self.parts:self.assertIsNone(rec.accept(part,100.01))

    def test_missing_fragment_no_partial_delivery(self):
        rec=assembler()
        for part in self.parts[:-1]:self.assertIsNone(rec.accept(part,0.))
        rec.poll(.201)
        self.assertIsNone(rec.active)
        self.assertIsNone(rec.accept(self.parts[-1],.202))

    def test_duplicate_never_extends_first_deadline(self):
        rec=assembler();rec.accept(self.parts[0],0.)
        rec.accept(self.parts[0],.19)
        for part in self.parts[1:]:self.assertIsNone(rec.accept(part,.201))
        self.assertEqual(rec.counts['expired'],1)
        self.assertIsNone(rec.active)

    def test_conflicting_duplicate_and_corrupt_packet_cleared(self):
        rec=assembler();rec.accept(self.parts[0],0.)
        rec.accept(self.parts[0][:-1]+bytes([self.parts[0][-1]^1]),.01)
        self.assertIsNone(rec.active)
        rec=assembler()
        for i,part in enumerate(self.parts):
            if i==1:part=part[:-1]+bytes([part[-1]^1])
            self.assertIsNone(rec.accept(part,0.))
        self.assertEqual(rec.counts['invalid'],1)

    def test_new_sequence_replaces_old_and_late_old_cannot_revive(self):
        newer=list(flow.fragments(png.encode_packet(self.image,candidate(sequence=2))))
        rec=assembler();rec.accept(self.parts[0],0.);rec.accept(newer[0],.01)
        for part in self.parts[1:]:self.assertIsNone(rec.accept(part,.02))
        for part in newer[1:]:result=rec.accept(part,.03)
        self.assertIsNotNone(result)
        self.assertEqual(rec.counts['replaced'],1)

    def test_fragment_fields_scope_magic_length_count_total(self):
        fields=list(flow.HEADER.unpack_from(self.parts[0]))
        for index,value in ((0,b'THFRAG1\0'),(1,b'z'*16),(2,b'z'*16),(3,0),
                            (4,png.MAX_PACKET+1),(5,65535),(6,1)):
            modified=fields.copy();modified[index]=value
            rec=assembler();self.assertIsNone(rec.accept(flow.HEADER.pack(*modified)+self.parts[0][flow.HEADER.size:],0.))
            self.assertIsNone(rec.active);self.assertEqual(rec.counts['invalid'],1)
        for part in (b'',self.parts[0][:-1],self.parts[0]+b'x'):
            self.assertIsNone(assembler().accept(part,0.))

    def test_fragment_envelope_must_match_inner_candidate(self):
        rec=assembler()
        for part in self.parts:
            fields=list(flow.HEADER.unpack_from(part));fields[3]=2
            self.assertIsNone(rec.accept(flow.HEADER.pack(*fields)+part[flow.HEADER.size:],0.))
        self.assertEqual(rec.counts['invalid'],1)

    def test_fragment_clock_retire_and_idle_expiry(self):
        rec=assembler();rec.accept(self.parts[0],1.);rec.poll(.9)
        self.assertTrue(rec.closed);self.assertIsNone(rec.active)
        self.assertIsNone(rec.accept(self.parts[1],1.1))
        rec=assembler();rec.close();self.assertIsNone(rec.accept(self.parts[0],0.))


if __name__=='__main__':unittest.main()
