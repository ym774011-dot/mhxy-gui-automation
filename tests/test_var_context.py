"""测试变量上下文管理"""
import pytest
from models.var_context import VarContext


class TestVarContext:
    """变量上下文测试类"""

    # ============================================================
    # 1. 基础变量操作测试
    # ============================================================

    def test_set_and_get_variable(self):
        """测试变量设置和获取"""
        var_ctx = VarContext()
        var_ctx.set("test_var", 123)
        assert var_ctx.get("test_var") == 123

    def test_update_variable(self):
        """测试变量更新"""
        var_ctx = VarContext()
        var_ctx.set("test_var", 123)
        var_ctx.update("test_var", 456)
        assert var_ctx.get("test_var") == 456

    def test_clear_variable(self):
        """测试变量清空"""
        var_ctx = VarContext()
        var_ctx.set("test_var", 123)
        var_ctx.clear("test_var")
        assert var_ctx.get("test_var") is None

    def test_clear_all_variables(self):
        """测试清空所有变量"""
        var_ctx = VarContext()
        var_ctx.set("var1", 123)
        var_ctx.set("var2", 456)
        var_ctx.clear()
        assert len(var_ctx._variables) == 0

    # ============================================================
    # 2. 变量模板替换测试
    # ============================================================

    def test_template_replacement(self):
        """测试变量模板替换"""
        var_ctx = VarContext()
        var_ctx.set("x", 100)
        var_ctx.set("y", 200)

        template = "坐标: ${x}, ${y}"
        result = var_ctx.replace(template)
        assert result == "坐标: 100, 200"

    def test_nested_access(self):
        """测试嵌套访问"""
        var_ctx = VarContext()
        var_ctx.set("result", {"x": 100, "y": 200})

        x = var_ctx.get("result.x")
        assert x == 100

    def test_nested_list_access(self):
        """测试嵌套列表访问"""
        var_ctx = VarContext()
        var_ctx.set("result", {"target_coord": [100, 200]})

        # 测试访问嵌套属性
        coord_0 = var_ctx.get("result.target_coord.0")
        coord_1 = var_ctx.get("result.target_coord.1")

        assert coord_0 == 100
        assert coord_1 == 200

    def test_template_replacement_with_nested_vars(self):
        """测试包含嵌套变量的模板替换"""
        var_ctx = VarContext()
        var_ctx.set("result", {"x": 100, "y": 200})

        template = "坐标: ${result.x}, ${result.y}"
        result = var_ctx.replace(template)
        assert result == "坐标: 100, 200"

    # ============================================================
    # 3. 异常场景测试
    # ============================================================

    def test_variable_not_found(self):
        """测试变量不存在"""
        var_ctx = VarContext()
        assert var_ctx.get("non_existent") is None

    def test_variable_not_found_with_default(self):
        """测试变量不存在时返回默认值"""
        var_ctx = VarContext()
        assert var_ctx.get("non_existent", "default") == "default"

    def test_invalid_template(self):
        """测试无效模板格式"""
        var_ctx = VarContext()
        template = "坐标: ${invalid"
        result = var_ctx.replace(template)
        assert result == template  # 无效模板不替换

    def test_template_with_nonexistent_variable(self):
        """测试模板中包含不存在的变量"""
        var_ctx = VarContext()
        template = "坐标: ${x}, ${y}"
        result = var_ctx.replace(template)
        # 不存在的变量保持原样
        assert "${x}" in result
        assert "${y}" in result

    def test_nested_access_invalid_path(self):
        """测试无效的嵌套路径"""
        var_ctx = VarContext()
        var_ctx.set("result", {"x": 100})

        # 访问不存在的嵌套属性
        assert var_ctx.get("result.z") is None

    def test_nested_access_invalid_index(self):
        """测试无效的列表索引"""
        var_ctx = VarContext()
        var_ctx.set("list", [1, 2, 3])

        # 访问超出范围的索引
        assert var_ctx.get("list.10") is None

    # ============================================================
    # 4. 其他测试
    # ============================================================

    def test_contains_operator(self):
        """测试包含操作符"""
        var_ctx = VarContext()
        var_ctx.set("x", 100)

        assert "x" in var_ctx
        assert "y" not in var_ctx

    def test_len_operator(self):
        """测试长度操作符"""
        var_ctx = VarContext()
        assert len(var_ctx) == 0

        var_ctx.set("x", 100)
        var_ctx.set("y", 200)
        assert len(var_ctx) == 2

    def test_repr(self):
        """测试字符串表示"""
        var_ctx = VarContext()
        var_ctx.set("x", 100)
        assert "VarContext" in repr(var_ctx)