"""11/14 operations helper tests: dummy metadata and bytes, no hardware."""
import hashlib
import importlib.util
import argparse
import json
from pathlib import Path
import struct
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('submission_pack',ROOT/'Experimental_results/2026-11-14/guarded_display_operations_r01/pack_submission.py')
pack=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(pack)


class SubmissionPackTests(unittest.TestCase):
    def fixture(self,root):
        primary=root/'Experimental_results/2026-11-14/driver_body_guard_live_r01';primary.mkdir(parents=True)
        comparison=root/'recordings/2026-11-14/body_guard_live_r01';comparison.mkdir(parents=True)
        png=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'+struct.pack('>II',1280,720)+b'synthetic header fixture, not decoded pixels'
        stem='decoded_'+('a'*32)+'_f000100'
        pin=dict(schema='driver_guarded_pin_v1',session='a'*32,frame=100,request_id=1,image_file=stem+'.png',image_size=[1280,720],image_modified=False,
            png_sha256=hashlib.sha256(png).hexdigest(),physical_metric_verified=False,floor_contact_verified=False,usable_for_ffb=False)
        status=dict(schema='driver_guarded_comparison_status_v1',state='pinned',writer_done=False,error=None,pin=pin,request_action='pin',request_id=1,
            status_time_sec=10.02,latest=dict(session='a'*32,frame=101,source_time_sec=10.01,reason='comparison_pin_requested',reference_scope_verified=False),
            **{k:False for k in (*pack.FLAGS,'main_display_modified')})
        (comparison/'comparison_status.json').write_text(json.dumps(status))
        (comparison/(stem+'.png')).write_bytes(png);(comparison/(stem+'.json')).write_text(json.dumps(pin))
        engine=dict(schema='driver_motion_engine_v1',body_display_guard=dict(enabled=True,display_rejection_only=True,raw_main_result_modified=False),
            guarded_comparison=dict(directory=str(comparison)),
            physical_metric_verified=False,usable_for_ffb=False,published_to_ros=False)
        (primary/'motion_engine_summary.json').write_text(json.dumps(engine))
        return primary,comparison,status,stem

    def complete(self,primary,comparison,status):
        status.update(state='closed',writer_done=True,shutdown_complete=True,latest=None)
        (comparison/'comparison_status.json').write_text(json.dumps(status))
        for name in ('comparison_frames.jsonl','reference.json','request.json'):(comparison/name).write_bytes(b'{}\n')
        for name in pack.PRIMARY:
            if not (primary/name).exists():(primary/name).write_bytes(b'{}\n')
        summary=dict(shutdown_complete=True,child_stopped=True,io_thread_stopped=True,
            worker_error=None,shutdown_error=None,forced_worker_kill=False,
            physical_metric_verified=False,usable_for_ffb=False,distance_published_to_ros=False,control_channel_modified=False)
        (primary/'driver_motion_summary.json').write_text(json.dumps(summary))

    def test_pin_only_latest_four_files_and_sources_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);primary,comparison,s,stem=self.fixture(root)
            (comparison/'decoded_old_f000010.png').write_bytes(b'old never selected')
            before={p:p.read_bytes() for base in (primary,comparison) for p in base.iterdir()}
            output=root/'pin.tar.xz'
            result=pack.package('pin',root,primary,comparison,output,now=10.03)
            self.assertEqual(result['files'],4)
            with tarfile.open(output,'r:xz') as archive:
                names=archive.getnames();self.assertEqual(len(names),4)
                self.assertTrue(all('old' not in name for name in names))
                self.assertEqual(archive.extractfile('body_guard_pin_submit/'+stem+'.png').read(),before[comparison/(stem+'.png')])
                self.assertEqual(archive.extractfile('body_guard_pin_submit/comparison_status.json').read(),before[comparison/'comparison_status.json'])
            self.assertTrue(all(p.read_bytes()==blob for p,blob in before.items()))

    def test_gap_stale_or_not_pinned_refused_without_output(self):
        for label in ('gap','stale','closed'):
            with self.subTest(label=label),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);primary,comparison,s,stem=self.fixture(root)
                if label=='gap':s['latest']['reason']='comparison_input_gap'
                elif label=='stale':s['status_time_sec']=8.
                else:s.update(state='closed',writer_done=True)
                (comparison/'comparison_status.json').write_text(json.dumps(s))
                with self.assertRaises(ValueError):pack.package('pin',root,primary,comparison,root/'out.tar.xz',now=10.03)
                self.assertFalse((root/'out.tar.xz').exists())
                self.assertFalse(list(root.glob('.theta_submission_*')))

    def test_sidecar_pixel_hash_or_authority_mismatch_refused(self):
        for label in ('sidecar','hash','authority'):
            with self.subTest(label=label),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);primary,comparison,s,stem=self.fixture(root)
                if label=='sidecar':(comparison/(stem+'.json')).write_bytes(b'{}')
                elif label=='hash':(comparison/(stem+'.png')).write_bytes(b'changed')
                else:
                    s['usable_for_ffb']=True;(comparison/'comparison_status.json').write_text(json.dumps(s))
                with self.assertRaises(ValueError):pack.package('pin',root,primary,comparison,root/'out.tar.xz',now=10.03)

    def test_existing_archive_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);primary,comparison,s,stem=self.fixture(root)
            output=root/'out.tar.xz';output.write_bytes(b'keep existing archive')
            with self.assertRaises(ValueError):pack.package('pin',root,primary,comparison,output,now=10.03)
            self.assertEqual(output.read_bytes(),b'keep existing archive')

    def test_input_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);primary,comparison,s,stem=self.fixture(root)
            original=comparison/(stem+'.png');original.rename(root/'original.png');original.symlink_to(root/'original.png')
            with self.assertRaises(OSError):pack.package('pin',root,primary,comparison,root/'out.tar.xz',now=10.03)
            self.assertFalse((root/'out.tar.xz').exists())

    def test_closed_package_preserves_paths_and_every_input_byte(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);primary,comparison,s,stem=self.fixture(root);self.complete(primary,comparison,s)
            inputs={p.relative_to(root).as_posix():p.read_bytes() for base in (primary,comparison) for p in base.iterdir()}
            result=pack.package('closed',root,primary,comparison,root/'full.tar.xz')
            with tarfile.open(root/'full.tar.xz','r:xz') as archive:
                actual={item.name:archive.extractfile(item).read() for item in archive.getmembers()}
            self.assertEqual(actual,inputs);self.assertEqual(result['files'],len(inputs))

    def test_live_worker_or_incomplete_primary_cannot_be_full_packaged(self):
        for label in ('live','primary'):
            with self.subTest(label=label),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);primary,comparison,s,stem=self.fixture(root);self.complete(primary,comparison,s)
                if label=='live':s.update(state='active',writer_done=False);(comparison/'comparison_status.json').write_text(json.dumps(s))
                else:(primary/'driver_motion_summary.json').write_text(json.dumps(dict(shutdown_complete=False)))
                with self.assertRaises(ValueError):pack.package('closed',root,primary,comparison,root/'full.tar.xz')
                self.assertFalse((root/'full.tar.xz').exists())

    def test_missing_or_unexpected_full_file_refused(self):
        for label in ('missing','unexpected'):
            with self.subTest(label=label),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);primary,comparison,s,stem=self.fixture(root);self.complete(primary,comparison,s)
                if label=='missing':(comparison/'reference.json').rename(comparison/'moved.json')
                else:(comparison/'request.json.part').write_bytes(b'partial')
                with self.assertRaises(ValueError):pack.package('closed',root,primary,comparison,root/'full.tar.xz')
                self.assertFalse((root/'full.tar.xz').exists())

    def test_output_inside_input_and_repository_root_as_run_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);primary,comparison,s,stem=self.fixture(root)
            with self.assertRaises(ValueError):pack.package('pin',root,primary,comparison,comparison/'out.tar.xz',now=10.03)
            with self.assertRaises(ValueError):pack.package('pin',root,root,comparison,root/'out.tar.xz',now=10.03)

    def test_duplicate_json_and_wrong_mode_rejected(self):
        with self.assertRaises(ValueError):pack.parse(b'{"state":1,"state":2}')
        with self.assertRaises(ValueError):pack.parse(b'{"source_time_sec":NaN}')
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);primary,comparison,s,stem=self.fixture(root)
            with self.assertRaises(ValueError):pack.package('unknown',root,primary,comparison,root/'out.tar.xz',now=10.03)

    def test_mixed_primary_comparison_and_closed_authority_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);primary,comparison,s,stem=self.fixture(root)
            engine=json.loads((primary/'motion_engine_summary.json').read_bytes())
            engine['guarded_comparison']['directory']=str(root/'different')
            (primary/'motion_engine_summary.json').write_text(json.dumps(engine))
            with self.assertRaises(ValueError):pack.package('pin',root,primary,comparison,root/'pin.tar.xz',now=10.03)
            engine['guarded_comparison']['directory']=str(comparison)
            (primary/'motion_engine_summary.json').write_text(json.dumps(engine));self.complete(primary,comparison,s)
            summary=json.loads((primary/'driver_motion_summary.json').read_bytes());summary['usable_for_ffb']=True
            (primary/'driver_motion_summary.json').write_text(json.dumps(summary))
            with self.assertRaises(ValueError):pack.package('closed',root,primary,comparison,root/'full.tar.xz')

    def test_publication_race_keeps_other_archive_and_cleans_only_temporary_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);primary,comparison,s,stem=self.fixture(root);output=root/'out.tar.xz'
            def occupied(source,destination):
                output.write_bytes(b'other writer owns this archive')
                raise FileExistsError('racing output already exists')
            with patch.object(pack.os,'link',side_effect=occupied),self.assertRaises(FileExistsError):
                pack.package('pin',root,primary,comparison,output,now=10.03)
            self.assertEqual(output.read_bytes(),b'other writer owns this archive')
            self.assertFalse(list(root.glob('.theta_submission_*')))

    def test_all_eight_document_shell_blocks_parse_without_execution(self):
        document=Path(pack.__file__).with_name('README.md').read_text()
        blocks=re.findall(r'```bash\n(.*?)```',document,re.S);self.assertEqual(len(blocks),8)
        for block in blocks:subprocess.run(['bash','-n'],input=block,text=True,check=True,capture_output=True)

    def test_document_receiver_and_pack_commands_use_same_new_run(self):
        sys.path.insert(0,str(ROOT/'src'))
        from driver_motion_bridge import add_motion_arguments
        blocks=re.findall(r'```bash\n(.*?)```',Path(pack.__file__).with_name('README.md').read_text(),re.S)
        command=re.search(r'bash src/start_theta_receive_rtc.sh (.*?)\nfi',blocks[0],re.S).group(1)
        parser=argparse.ArgumentParser();add_motion_arguments(parser)
        args=parser.parse_args(shlex.split(command.replace('\\\n',' ')))
        self.assertTrue(args.motion_distance and args.motion_body_display_guard and args.motion_experimental_rigid_mount)
        self.assertEqual(args.motion_target_roi,[270,0,350,720])
        for index,mode in ((4,'pin'),(7,'closed')):
            tokens=shlex.split(blocks[index].replace('\\\n',' '));self.assertIn(mode,tokens)
            self.assertEqual(Path(tokens[tokens.index('--primary-dir')+1]),args.motion_output_dir)
            self.assertEqual(Path(tokens[tokens.index('--comparison-dir')+1]),args.motion_comparison_dir)
        self.assertIn('2026-11-14',str(args.motion_output_dir))


if __name__=='__main__':unittest.main()
