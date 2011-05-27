# -*- coding: utf-8 -*-
import os
import unittest
from subprocess import Popen, PIPE

from testcpybuilder import BuiltModule, PyRuntime, SimpleModule, CompilationError
from cpybuilder import PyMethodTable, PyMethodDef, METH_VARARGS

#FIXME:
pyruntime = PyRuntime('/usr/bin/python2.7', '/usr/bin/python2.7-config')

class ExpectedErrorNotFound(CompilationError):
    def __init__(self, expected_err, actual_err, bm):
        CompilationError.__init__(self, bm)
        self.expected_err = expected_err
        self.actual_err = actual_err


    def _describe_activity(self):
        result = 'This error was expected, but was not found:\n'
        result += '  ' + self._indent(self.expected_err) + '\n'
        result += '  whilst compiling:\n'
        result += '    ' + self.bm.srcfile + '\n'
        result += '  using:\n'
        result += '    ' + ' '.join(self.bm.args) + '\n'
        
        from difflib import unified_diff
        for line in unified_diff(self.expected_err.splitlines(),
                                 self.actual_err.splitlines(),
                                 fromfile='Expected stderr',
                                 tofile='Actual stderr',
                                 lineterm=""):
            result += '%s\n' % line
        return result

class AnalyzerTests(unittest.TestCase):
    def compile_src(self, bm):
        bm.compile_src(extra_cflags=['-fplugin=%s' % os.path.abspath('python.so'),
                                     '-fplugin-arg-python-script=cpychecker.py'])

    def build_module(self, bm):
        bm.write_src()
        self.compile_src(bm)

    def assertNoErrors(self, src):
        if isinstance(src, SimpleModule):
            sm = src
        else:
            sm = SimpleModule()
            sm.cu.add_defn(src)
        bm = BuiltModule(sm, pyruntime)
        self.build_module(bm)
        bm.cleanup()
        return bm

    def assertFindsError(self, src, experr):
        if isinstance(src, SimpleModule):
            sm = src
        else:
            sm = SimpleModule()
            sm.cu.add_defn(src)
        bm = BuiltModule(sm, pyruntime)
        try:
            bm.write_src()
            experr = experr.replace('$(SRCFILE)', bm.srcfile)
            self.compile_src(bm)
        except CompilationError, exc:
            if experr not in exc.err:
                raise ExpectedErrorNotFound(experr, exc.err, bm)
        else:
            raise ExpectedErrorNotFound(experr, bm.err, bm)
        bm.cleanup()
        return bm

class PyArg_ParseTupleTests(AnalyzerTests):
    def test_bogus_format_string(self):
        src = ('PyObject *\n'
               'bogus_format_string(PyObject *self, PyObject *args)\n'
               '{\n'
               '    if (!PyArg_ParseTuple(args, "This is not a valid format string")) {\n'
               '  	    return NULL;\n'
               '    }\n'
               '    Py_RETURN_NONE;\n'
               '}\n')
        experr = ('$(SRCFILE): In function ‘bogus_format_string’:\n'
                  '$(SRCFILE):12:26: error: unknown format char in "This is not a valid format string": \'T\' [-fpermissive]\n')
        self.assertFindsError(src, experr)
                   
    def test_finding_htons_error(self):
        #  Erroneous argument parsing of socket.htons() on 64bit big endian
        #  machines from CPython's Modules/socket.c; was fixed in svn r34931
        #  FIXME: the original had tab indentation, but what does this mean
        # for "column" offsets in the output?
        src = """
extern uint16_t htons(uint16_t hostshort);

PyObject *
socket_htons(PyObject *self, PyObject *args)
{
    unsigned long x1, x2;

    if (!PyArg_ParseTuple(args, "i:htons", &x1)) {
        return NULL;
    }
    x2 = (int)htons((short)x1);
    return PyInt_FromLong(x2);
}
"""
        self.assertFindsError(src,
                              '$(SRCFILE): In function ‘socket_htons’:\n'
                              '$(SRCFILE):17:26: error: Mismatching type in call to PyArg_ParseTuple with format string "i:htons":'
                              ' argument 3 ("&x1") had type "long unsigned int *" (pointing to 64 bits)'
                              ' but was expecting "int *" (pointing to 32 bits) for format code "i"'
                              ' [-fpermissive]\n')

    def test_not_enough_varargs(self):
        src = """
PyObject *
not_enough_varargs(PyObject *self, PyObject *args)
{
   if (!PyArg_ParseTuple(args, "i")) {
       return NULL;
   }
   Py_RETURN_NONE;
}
"""
        self.assertFindsError(src,
                              '$(SRCFILE): In function ‘not_enough_varargs’:\n'
                              '$(SRCFILE):13:25: error: Not enough arguments in call to PyArg_ParseTuple with format string "i" : expected 1 extra arguments (int *), but got 0 [-fpermissive]\n')

    def test_too_many_varargs(self):
        src = """
PyObject *
too_many_varargs(PyObject *self, PyObject *args)
{
    int i, j;
    if (!PyArg_ParseTuple(args, "i", &i, &j)) {
	 return NULL;
    }
    Py_RETURN_NONE;
}
"""
        self.assertFindsError(src,
                              '$(SRCFILE): In function ‘too_many_varargs’:\n'
                              '$(SRCFILE):14:26: error: Too many arguments in call to PyArg_ParseTuple with format string "i" : expected 1 extra arguments (int *), but got 2 [-fpermissive]\n')

    def test_correct_usage(self):
        src = """
PyObject *
correct_usage(PyObject *self, PyObject *args)
{
    int i;
    if (!PyArg_ParseTuple(args, "i", &i)) {
	 return NULL;
    }
    Py_RETURN_NONE;
}
"""
        self.assertNoErrors(src)

    def get_function_name(self, header, code):
        name = '%s_%s' % (header, code)
        name = name.replace('*', '_star')
        name = name.replace('#', '_hash')
        name = name.replace('!', '_bang')
        name = name.replace('&', '_amp')
        return name

    def make_src_for_correct_function(self, code, typenames, params=None):
        # Generate a C function that uses the format code correctly, and verify
        # that it compiles with gcc with the cpychecker script, without errors
        function_name = self.get_function_name('correct_usage_of', code)
        src = ('PyObject *\n'
               '%(function_name)s(PyObject *self, PyObject *args)\n'
               '{\n') % locals()
        for i, typename in enumerate(typenames):
            src += ('    %(typename)s val%(i)s;\n') % locals()
        if not params:
            params = ', '.join('&val%i' % i for i in range(len(typenames)))
        src += ('    if (!PyArg_ParseTuple(args, "%(code)s", %(params)s)) {\n'
                '              return NULL;\n'
                '    }\n'
                '    Py_RETURN_NONE;\n'
                '}\n') % locals()
        return src

    def make_src_for_incorrect_function(self, code, typenames):
        function_name = self.get_function_name('incorrect_usage_of', code)
        params = ', '.join('&val' for i in range(len(typenames)))
        src = ('PyObject *\n'
               '%(function_name)s(PyObject *self, PyObject *args)\n'
               '{\n'
               '    void *val;\n'
               '    if (!PyArg_ParseTuple(args, "%(code)s", %(params)s)) {\n'
               '  	    return NULL;\n'
               '    }\n'
               '    Py_RETURN_NONE;\n'
               '}\n') % locals()
        return src, function_name

    def get_funcname(self):
        return 'PyArg_ParseTuple'

    def get_expected_error(self):
        return ('$(SRCFILE): In function ‘%(function_name)s’:\n'
                '$(SRCFILE):13:26: error: Mismatching type in call to %(funcname)s with format string "%(code)s": argument 3 ("&val") had type "void * *" but was expecting "%(exptypename)s *"')

    def _test_format_code(self, code, typenames, exptypenames=None):
        if not exptypenames:
            exptypenames = typenames

        if isinstance(typenames, str):
            typenames = [typenames]
        if isinstance(exptypenames, str):
            exptypenames = [exptypenames]

        def _test_correct_usage_of_format_code(self, code, typenames):
            src = self.make_src_for_correct_function(code, typenames)
            self.assertNoErrors(src)

        def _test_incorrect_usage_of_format_code(self, code, typenames, exptypenames):
            # Generate a C function that uses the format code, with the
            # correct number of arguments, but all of the arguments being of
            # the incorrect type; compile it with cpychecker, and verify that there's
            # a warning
            exptypename = exptypenames[0]
            src, function_name = self.make_src_for_incorrect_function(code, typenames)
            funcname = self.get_funcname()
            experr = self.get_expected_error() % locals()
            bm = self.assertFindsError(src, experr)
                                       
        _test_correct_usage_of_format_code(self, code, typenames)
        _test_incorrect_usage_of_format_code(self, code, typenames, exptypenames)

    # The following test cases are intended to be in the same order as the API
    # documentation at http://docs.python.org/c-api/arg.html
        
    def test_format_code_s(self):
        self._test_format_code('s', 'const char *')

    def test_format_code_s_hash(self):
        self._test_format_code('s#', ['const char *', 'Py_ssize_t'])

    def test_format_code_s_star(self):
        self._test_format_code('s*', ['Py_buffer'])

    def test_format_code_z(self):
        self._test_format_code('z', 'const char *')

    def test_format_code_z_hash(self):
        self._test_format_code('z#', ['const char *', 'Py_ssize_t'])

    def test_format_code_z_star(self):
        self._test_format_code('z*', ['Py_buffer'])

    def test_format_code_u(self):
        self._test_format_code('u', 'Py_UNICODE *')

    def test_format_code_u_hash(self):
        self._test_format_code('u#', ['Py_UNICODE *', 'Py_ssize_t']) # not an int

    def test_format_code_es(self):
        self._test_format_code('es', ['const char', 'char *'])

    def test_format_code_et(self):
        self._test_format_code('et', ['const char', 'char *'])

    def test_format_code_es_hash(self):
        self._test_format_code('es#', ['const char', 'char *', 'int'])

    def test_format_code_et_hash(self):
        self._test_format_code('et#', ['const char', 'char *', 'int'])

    def test_format_code_b(self):
        self._test_format_code('b', 'unsigned char')

    def test_format_code_B(self):
        self._test_format_code('B', 'unsigned char')

    def test_format_code_h(self):
        self._test_format_code('h', 'short', 'short int')

    def test_format_code_H(self):
        self._test_format_code('H', 'unsigned short', 'short unsigned int')

    def test_format_code_i(self):
        self._test_format_code('i', 'int')

    def test_format_code_I(self):
        self._test_format_code('I', 'unsigned int')

    def test_format_code_l(self):
        self._test_format_code('l', 'long', 'long int')

    def test_format_code_k(self):
        self._test_format_code('k', 'unsigned long', 'long unsigned int')

    def test_format_code_L(self):
        self._test_format_code('L', 'PY_LONG_LONG', 'long long int')

    def test_format_code_K(self):
        self._test_format_code('K', 'unsigned PY_LONG_LONG', 'long long unsigned int')

    def test_format_code_n(self):
        self._test_format_code('n', 'Py_ssize_t')

    def test_format_code_c(self):
        self._test_format_code('c', 'char')

    def test_format_code_f(self):
        self._test_format_code('f', 'float')

    def test_format_code_d(self):
        self._test_format_code('d', 'double')

    def test_format_code_D(self):
        self._test_format_code('D', 'Py_complex')

    def test_format_code_O(self):
        self._test_format_code('O', ['PyObject *'])

    def test_format_code_O_bang(self):
        self._test_format_code('O!', ['PyTypeObject', 'PyObject *'])

    def test_format_code_O_amp(self):
        # O& (object) [converter, anything]
        # Converter should be a function of the form:
        #   int conv(object, T* val_addr)
        # args should be: converter, T*
        src = self.make_src_for_correct_function('O&', ['int'],
                                                 params='my_converter, &val0')
        src = 'extern int my_converter(PyObject *obj, int *i);\n\n' + src
        # self.assertNoErrors(src)

        #self._test_format_code('O&', ['PyTypeObject', 'PyObject *'])
        #self.assert_args("O&",
        #                 ['int ( PyObject * object , int * target )',
        #                  'int *',
        #                  'int *'])

    def test_format_code_S(self):
        self._test_format_code('S', ['PyStringObject *'])

    def test_format_code_U(self):
        self._test_format_code('U', ['PyUnicodeObject *'])

    def test_format_code_t_hash(self):
        self._test_format_code('t#', ['char *', 'Py_ssize_t'])

    def test_format_code_w(self):
        self._test_format_code('w', 'char *')

    def test_format_code_w_hash(self):
        self._test_format_code('w#', ['char *', 'Py_ssize_t'])

    def test_format_code_w_star(self):
        self._test_format_code('w*', ['Py_buffer'])

    def test_mismatched_parentheses(self):
        for code in ['(', ')', '(()']:
            function_name = 'fn'
            src = ('PyObject *\n'
                   '%(function_name)s(PyObject *self, PyObject *args)\n'
                   '{\n') % locals()
            src += ('    if (!PyArg_ParseTuple(args, "%(code)s")) {\n'
                    '              return NULL;\n'
                    '    }\n'
                    '    Py_RETURN_NONE;\n'
                    '}\n') % locals()
            experr = ('$(SRCFILE): In function ‘%(function_name)s’:\n'
                      '$(SRCFILE):12:26: error: mismatched parentheses in format string "%(code)s"' % locals())
            bm = self.assertFindsError(src, experr)

class PyArg_ParseTupleAndKeywordsTests(PyArg_ParseTupleTests):
    def get_funcname(self):
        return 'PyArg_ParseTupleAndKeywords'

    def get_expected_error(self):
        return ('$(SRCFILE): In function ‘%(function_name)s’:\n'
                '$(SRCFILE):14:37: error: Mismatching type in call to %(funcname)s with format string "%(code)s": argument 5 ("&val") had type "void * *" but was expecting "%(exptypename)s *"')

    def make_src_for_correct_function(self, code, typenames, params=None):
        # Generate a C function that uses the format code correctly, and verify
        # that it compiles with gcc with the cpychecker script, without errors
        function_name = self.get_function_name('correct_usage_of', code)
        src = ('PyObject *\n'
               '%(function_name)s(PyObject *self, PyObject *args, PyObject *kw)\n'
               '{\n') % locals()
        src += '    char *keywords[] = {"fake_keyword", NULL};\n'
        for i, typename in enumerate(typenames):
            src += ('    %(typename)s val%(i)s;\n') % locals()
        if not params:
            params = ', '.join('&val%i' % i for i in range(len(typenames)))
        src += ('    if (!PyArg_ParseTupleAndKeywords(args, kw, "%(code)s", keywords, %(params)s)) {\n'
                '              return NULL;\n'
                '    }\n'
                '    Py_RETURN_NONE;\n'
                '}\n') % locals()
        return src

    def make_src_for_incorrect_function(self, code, typenames):
        function_name = self.get_function_name('incorrect_usage_of', code)
        params = ', '.join('&val' for i in range(len(typenames)))
        src = ('PyObject *\n'
               '%(function_name)s(PyObject *self, PyObject *args, PyObject *kw)\n'
               '{\n'
               '    void *val;\n'
               '    char *keywords[] = {"fake_keyword", NULL};\n'
               '    if (!PyArg_ParseTupleAndKeywords(args, kw, "%(code)s", keywords, %(params)s)) {\n'
               '        return NULL;\n'
               '    }\n'
               '    Py_RETURN_NONE;\n'
               '}\n') % locals()
        return src, function_name

@unittest.skip("Refcount tracker doesn't yet work")
class RefcountErrorTests(AnalyzerTests):
    def add_method_table(self, cu, fn_name):
        methods = PyMethodTable('test_methods',
                                [PyMethodDef('test_method', fn_name,
                                             METH_VARARGS, None)])
        cu.add_defn(methods.c_defn())
        return methods

    def add_module(self, sm, methods):
        sm.add_module_init('buggy', modmethods=methods, moddoc=None)

    def make_mod_method(self, function_name, body):
        sm = SimpleModule()
        sm.cu.add_defn(
            'int val;\n'
            'PyObject *\n'
            '%(function_name)s(PyObject *self, PyObject *args)\n' % locals()
            +'{\n'
            + body
            + '}\n')
        methods = self.add_method_table(sm.cu, function_name)
        self.add_module(sm, methods)
        return sm

    def test_correct_py_none(self):
        sm = self.make_mod_method('correct_none',
            '    Py_RETURN_NONE;\n')
        self.assertNoErrors(sm)

    def test_correct_object_ctor(self):
        sm = self.make_mod_method('correct_object_ctor',
            '    /* This code is correct: the API call returns a \n'
            '       new reference.  Use some temporaries to make things more\n'
            '       difficult for the checker.: */\n'
            '    PyObject *tmpA;\n'
            '    PyObject *tmpB;\n'
            '    tmpA = PyLong_FromLong(0x1000);\n'
            '    tmpB = tmpA;\n'
            '    return tmpB;\n')
        self.assertNoErrors(sm)

    def test_too_many_increfs(self):
        sm = self.make_mod_method('too_many_increfs',
            '    PyObject *tmp;\n'
            '    tmp = PyLong_FromLong(0x1000);\n'
            '    /* This INCREF is redundant, and introduces a leak: */\n'
            '    Py_INCREF(tmp);\n'
            '    return tmp;\n')
        experr = ('$(SRCFILE): In function ‘too_many_increfs’:\n'
                  '$(SRCFILE):19:5: error: additional Py_INCREF() [-fpermissive]\n'
                  )
        self.assertFindsError(sm, experr)

    def test_missing_decref(self):
        sm = self.make_mod_method('missing_decref',
            '    PyObject *list;\n'
            '    PyObject *item;\n'
            '    list = PyList_New(1);\n'
            '    if (!list)\n'
            '        return NULL;\n'
            '    item = PyLong_FromLong(42);\n'
            '    /* This error handling is incorrect: it\'s missing an\n'
            '       invocation of Py_DECREF(list): */\n'
            '    if (!item)\n'
            '        return NULL;\n'
            '    PyList_SetItem(list, 0, item);\n'
            '    return list;\n')
        experr = ('$(SRCFILE): In function ‘missing_decref’:\n'
                  '$(SRCFILE):19:5: error: missing Py_DECREF() [-fpermissive]\n')
        self.assertFindsError(sm, experr)

    #@unittest.skip("Refcount tracker doesn't yet work")
    def test_incorrect_py_none(self):
        sm = self.make_mod_method('losing_refcnt_of_none',
            '    /* Bug: this code is missing a Py_INCREF on Py_None */\n'
            '    return Py_None;\n'
            '}\n')
        experr = ('$(SRCFILE): In function ‘losing_refcnt_of_none’:\n'
                  '$(SRCFILE):19:5: error: return of PyObject* without Py_INCREF() [-fpermissive]\n'
                  )
        self.assertFindsError(sm, experr)

# Test disabled for now: we can't easily import this under gcc anymore:
class TestArgParsing: # (unittest.TestCase):
    def assert_args(self, arg_str, exp_result):
        result = get_types(None, arg_str)
        self.assertEquals(result, exp_result)

    def test_fcntlmodule_fcntl_flock(self):
        # FIXME: somewhat broken, we can't know what the converter callback is
        self.assert_args("O&i:flock", 
                         ['int ( PyObject * object , int * target )', 
                          'int *', 
                          'int *'])

    def test_bsddb_DBSequence_set_range(self):
        self.assert_args("(LL):set_range",
                         ['PY_LONG_LONG *', 'PY_LONG_LONG *'])


if __name__ == '__main__':
    unittest.main()
