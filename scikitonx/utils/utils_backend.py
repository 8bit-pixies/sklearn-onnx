"""
Helpers to test runtimes.
"""
import os
import sys
import glob
import pickle
from distutils.version import StrictVersion
import numpy
from numpy.testing import assert_array_almost_equal, assert_array_equal


class ExpectedAssertionError(Exception):
    """
    Expected failure.
    """
    pass


class OnnxRuntimeAssertionError(AssertionError):
    """
    Expected failure.
    """
    pass
    

def evaluate_condition(backend, condition):
    """
    Evaluates a condition such as
    ``StrictVersion(onnxruntime.__version__) <= StrictVersion('0.1.3')``
    """
    if backend == "onnxruntime":
        import onnxruntime
        import onnx
        return eval(condition)
    else:
        raise NotImplementedError("Not implemented for backend '{0}'".format(backend))


def is_backend_enabled(backend):
    """
    Tells if a backend is enabled.
    """
    if backend == "onnxruntime":
        try:
            import onnxruntime
            return True
        except ImportError:
            return False
    else:
        raise NotImplementedError("Not implemented for backend '{0}'".format(backend))


def compare_backend(backend, test, decimal=5, options=None, verbose=False, context=None):
    """
    The function compares the expected output (computed with
    the model before being converted to ONNX) and the ONNX output
    produced with module *onnxruntime*.
    
    :param backend: backend to use to run the comparison,
        only *onnxruntime* is currently supported
    :param test: dictionary with the following keys:
        - *onnx*: onnx model (filename or object)
        - *expected*: expected output (filename pkl or object)
        - *data*: input data (filename pkl or object)
    :param decimal: precision of the comparison
    :param options: comparison options
    :param context: specifies custom operators
    :param verbose: in case of error, the function may print
        more information on the standard output
    
    The function does not return anything but raises an error
    if the comparison failed.
    """
    if backend == "onnxruntime":
        if sys.version_info[0] == 2:
            # onnxruntime is not available on Python 2.
            return            
        from .utils_backend_onnxruntime import compare_runtime
        return compare_runtime(test, decimal, options, verbose)
    else:
        raise ValueError("Does not support backend '{0}'.".format(backend))


def search_converted_models(root=None):
    """
    Searches for all converted models generated by
    unit tests in folders tests and with function
    *dump_data_and_model*.
    """
    if root is None:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "_dump_data"))
        root = os.path.normpath(root)
    if not os.path.exists(root):
    if not os.path.exists(root):
        raise FileNotFoundError("Unable to find '{0}'.".format(root))
    
    founds = glob.iglob("{0}/**/*.model.onnx".format(root), recursive=True)
    keep = []
    for found in founds:
        onnx = found
        basename = onnx[:-len(".model.onnx")]
        data = basename + ".data.pkl"
        expected = basename + ".expected.pkl"
        res = dict(onnx=onnx, data=data, expected=expected)
        ok = True
        for k, v in res.items():
            if not os.path.exists(v):
                ok = False
        if ok:
            models = [basename + ".model.pkl", basename + ".model.keras"]
            for model in models:
                if os.path.exists(model):
                    res['model'] = model
                    break
            if 'model' in res:
                keep.append((basename, res))
    keep.sort()
    return [_[1] for _ in keep]
    

def load_data_and_model(items_as_dict, **context):
    """
    Loads every file in a dictionary {key: filename}.
    The extension is either *pkl* and *onnx* and determines
    how it it loaded. If the value is not a string,
    the function assumes it was already loaded.
    """
    res = {}
    for k, v in items_as_dict.items():
        if isinstance(v, str):
            if os.path.splitext(v)[-1] == ".pkl":
                with open(v, "rb") as f:
                    try:
                        bin = pickle.load(f)
                    except ImportError as e:
                        if '.model.' in v:
                            continue
                        else:
                            raise ImportError("Unable to load '{0}' due to {1}".format(v, e))
                    res[k] = bin
            elif os.path.splitext(v)[-1] == ".keras":
                import keras.models
                res[k] = keras.models.load_model(v, custom_objects=context)
            else:
                res[k] = v
        else:
            res[k] = v
    return res


def extract_options(name):
    """
    Extracts comparison option from filename.
    As example, ``Binarizer-SkipDim1`` means
    options *SkipDim1* is enabled. 
    ``(1, 2)`` and ``(2,)`` are considered equal.
    Available options:

    * `'SkipDim1'`: reshape arrays by skipping 1-dimension: ``(1, 2)`` --> ``(2,)``
    * `'OneOff'`: inputs comes in a list for the predictions are computed with a call for each of them,
        not with one call
    * ...

    See function *dump_data_and_model* to get the full list.
    """
    opts = name.replace("\\", "/").split("/")[-1].split('.')[0].split('-')
    if len(opts) == 1:
        return {}
    else:
        res = {}
        for opt in opts[1:]:
            if opt in ("SkipDim1", "OneOff", "NoProb", "Dec4", "Dec3", 'Out0', 'Reshape'):
                res[opt] = True
            else:
                raise NameError("Unable to parse option '{}'".format(opts[1:]))
        return res


def compare_outputs(expected, output, **kwargs):
    """
    Compares expected values and output.
    Returns None if no error, an exception message otherwise.
    """
    SkipDim1 = kwargs.pop("SkipDim1", False)
    NoProb = kwargs.pop("NoProb", False)
    Dec4 = kwargs.pop("Dec4", False)
    Dec3 = kwargs.pop("Dec3", False)
    Disc = kwargs.pop("Disc", False)
    Mism = kwargs.pop("Mism", False)

    if Dec4:
        kwargs["decimal"] = min(kwargs["decimal"], 4)
    if Dec3:
        kwargs["decimal"] = min(kwargs["decimal"], 3)
    if isinstance(expected, numpy.ndarray) and isinstance(output, numpy.ndarray):
        if SkipDim1:
            # Arrays like (2, 1, 2, 3) becomes (2, 2, 3) as one dimension is useless.
            expected = expected.reshape(tuple([d for d in expected.shape if d > 1]))
            output = output.reshape(tuple([d for d in expected.shape if d > 1]))
        if NoProb:
            # One vector is (N,) with scores, negative for class 0
            # positive for class 1
            # The other vector is (N, 2) score in two columns.
            if len(output.shape) == 2 and output.shape[1] == 2 and len(expected.shape) == 1:
                output = output[:, 1]
            elif len(output.shape) == 1 and len(expected.shape) == 1:
                pass
            elif len(expected.shape) == 1 and len(output.shape) == 2 and \
                    expected.shape[0] == output.shape[0] and output.shape[1] == 1:
                output = output[:, 0]
            elif expected.shape != output.shape:
                raise NotImplementedError("No good shape: {0} != {1}".format(expected.shape, output.shape))
        if len(expected.shape) == 1 and len(output.shape) == 2 and output.shape[1] == 1:
            output = output.ravel()
        if expected.dtype in (numpy.str, numpy.dtype("<U1")):
            try:
                assert_array_equal(expected, output)
            except Exception as e:
                if Disc:
                    # Bug to be fixed later.
                    return ExpectedAssertionError(str(e))
                else:
                    return OnnxRuntimeAssertionError(str(e))
        else:
            try:
                assert_array_almost_equal(expected, output, **kwargs)
            except Exception as e:
                expected_ = expected.ravel()
                output_ = output.ravel()
                if len(expected_) == len(output_):
                    diff = numpy.abs(expected_ - output_).max()
                elif Mism:
                    return ExpectedAssertionError("dimension mismatch={0}, {1}\n{2}".format(expected.shape, output.shape, e))
                else:
                    return OnnxRuntimeAssertionError("dimension mismatch={0}, {1}\n{2}".format(expected.shape, output.shape, e))
                if Disc:
                    # Bug to be fixed later.
                    return ExpectedAssertionError("max diff(expected, output)={0}\n{1}".format(diff, e))
                else:
                    return OnnxRuntimeAssertionError("max diff(expected, output)={0}\n{1}".format(diff, e))
    else:
        return OnnxRuntimeAssertionError("Unexpected types {0} != {1}".format(type(expected), type(output)))
    return None
