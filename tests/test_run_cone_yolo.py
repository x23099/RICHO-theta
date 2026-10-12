from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from run_cone_yolo import build_parser,check_cuda,model_kwargs,validated_args


class ConeRunnerTest(unittest.TestCase):
    def args(self,mode='train',*extra):
        return build_parser().parse_args([mode,'--dataset','/tmp/cone_dataset_fixture_not_opened',
            '--output-dir','/tmp/cone_runner_preview_not_created',*extra])

    def test_training_never_uses_test_split(self):
        args=validated_args(self.args())
        kwargs=model_kwargs(args)
        self.assertNotIn('split',kwargs)
        self.assertFalse(kwargs['plots'])
        self.assertEqual(kwargs['flipud'],0.)
        self.assertEqual(kwargs['data'],str(args.dataset/'data.yaml'))

    def test_val_and_test_are_explicit(self):
        for mode in ('val','test'):
            args=self.args(mode,'--weights',str(Path(__file__).resolve().parents[1]/'src/yolov8n.pt'))
            self.assertEqual(model_kwargs(validated_args(args))['split'],mode)

    def test_evaluation_requires_explicit_checkpoint(self):
        with self.assertRaisesRegex(ValueError,'trained'): validated_args(self.args('val'))

    def test_model_must_be_local(self):
        with self.assertRaisesRegex(ValueError,'local trusted'):
            validated_args(self.args('env','--weights','/tmp/nonexistent_cone_weights.pt'))

    def test_invalid_training_settings(self):
        for key,value in (('--device','-1'),('--batch','0'),('--imgsz','641'),('--epochs','0')):
            with self.subTest(key=key),self.assertRaises(ValueError): validated_args(self.args('train',key,value))

    def test_existing_output_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'new output'): validated_args(self.args('env','--output-dir',directory))

    def test_output_and_dataset_do_not_overlap(self):
        args=self.args('train','--dataset','/tmp/cone_fixture_dataset','--output-dir','/tmp/cone_fixture_dataset/run')
        with self.assertRaisesRegex(ValueError,'overlap'): validated_args(args)

    def test_cuda_unavailable_does_not_fall_back_to_cpu(self):
        torch=Mock(); torch.cuda.is_available.return_value=False
        with self.assertRaisesRegex(ValueError,'no CPU fallback'): check_cuda(torch,0)

    def test_gpu_check_executes_cuda_tensor(self):
        torch=Mock(); torch.cuda.is_available.return_value=True; torch.cuda.device_count.return_value=1
        torch.cuda.get_device_name.return_value='SYNTHETIC TEST GPU'; torch.__version__='test'; torch.version.cuda='test'
        result=check_cuda(torch,0)
        self.assertEqual(result['index'],0)
        torch.ones.assert_called_once_with((2,2),device='cuda:0')


if __name__=='__main__': unittest.main()
