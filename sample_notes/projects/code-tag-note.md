# 正则表达式备忘

整理几个常忘的写法，顺手记下来，免得每次现查。

## 邮箱匹配

```python
import re

# 匹配邮箱：用户名 @ 域名
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# TODO: 域名部分还应限制 TLD 长度
#fixme: 下面的写法会误伤带加号的地址
```

行内代码里的 `#notatag` 不是标签，`#also-not-a-tag` 也不是。

## 常用片段

```python
# 提取所有 #hashtag 形式的词（注意：这行在代码块里，不算标签）
TAGS_RE = re.compile(r"#(\w+)")
```

正文里的标签才算数，比如这篇的 #python 和 #regex。
