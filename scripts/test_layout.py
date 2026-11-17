import unittest
from layout import layout_lines

class LayoutTests(unittest.TestCase):
    def test_names_stay_intact_and_duplicates_retained(self):
        names=['欧阳明月','司徒长风','阿依古丽·测试','张三','张三']*12
        rows=layout_lines([{'names':names}])
        self.assertEqual([n for line,_,_ in rows for n in line.split('　　')],names)
    def test_marked_delimited_names(self):
        names=['测试姓名甲','测试姓名乙','测试姓名丙']*8
        rows=layout_lines([{'text':'、'.join(names),'name_list':True}])
        self.assertEqual([n for line,_,_ in rows for n in line.split('　　')],names)
    def test_prose_punctuation_preserved(self):
        text='最幸福、难忘的瞬间'
        self.assertEqual(layout_lines([{'text':text}])[0][0],text)
    def test_reject_oversized_individual_name(self):
        with self.assertRaises(ValueError):layout_lines([{'names':['非常长的称谓'*8]}])
    def test_reject_empty_copy(self):
        with self.assertRaises(ValueError):layout_lines([{'text':''}])
if __name__=='__main__':unittest.main()
