import pytest

from nexus.capabilities.intelligence.nate.execution_graph import ExecutionGraph, ToolGraph


class TestToolGraph:
    @pytest.fixture
    def graph(self):
        g = ToolGraph()
        g.add_node("start", cost=0)
        g.add_node("weather", cost=1)
        g.add_node("calendar", cost=1)
        g.add_node("email", cost=1)
        g.add_node("finish", cost=0)
        g.add_edge("start", "weather", 1)
        g.add_edge("start", "email", 1)
        g.add_edge("weather", "calendar", 1)
        g.add_edge("calendar", "finish", 1)
        g.add_edge("email", "finish", 1)
        return g

    def test_shortest_path(self, graph):
        path, cost = graph.shortest_path("start", "finish")
        assert path is not None
        assert path[0] == "start"
        assert path[-1] == "finish"
        assert cost > 0

    def test_reroute_on_failure(self, graph):
        graph.mark_failed("weather")
        path, cost = graph.shortest_path("start", "finish")
        assert path is not None
        assert "weather" not in path
        assert "email" in path

    def test_all_failed_returns_none(self, graph):
        graph.mark_failed("weather")
        graph.mark_failed("email")
        path, cost = graph.shortest_path("start", "finish")
        assert path is None
        assert cost == float("inf")

    def test_no_path(self, graph):
        g = ToolGraph()
        g.add_node("a")
        g.add_node("b")
        path, cost = g.shortest_path("a", "b")
        assert path is None

    def test_recover_and_find_path(self, graph):
        graph.mark_failed("weather")
        graph.mark_failed("email")
        path, cost = graph.shortest_path("start", "finish")
        assert path is None
        graph.mark_recovered("weather")
        path, cost = graph.shortest_path("start", "finish")
        assert path is not None
        assert "weather" in path


class TestExecutionGraph:
    @pytest.fixture
    def exe_graph(self):
        eg = ExecutionGraph()
        eg.set_start("start")
        eg.set_goal("finish")
        eg.add_dependency("start", "weather", 1)
        eg.add_dependency("weather", "calendar", 1)
        eg.add_dependency("calendar", "finish", 1)
        return eg

    def test_plan(self, exe_graph):
        path, cost = exe_graph.plan()
        assert path is not None
        assert len(path) >= 2

    def test_reroute(self, exe_graph):
        exe_graph.graph.mark_failed("weather")
        path, cost = exe_graph.reroute()
        assert path is None or "weather" not in path

    def test_execute_with_handlers(self):
        eg = ExecutionGraph()
        eg.set_start("start")
        eg.set_goal("finish")
        eg.add_tool("weather", handler=lambda: "sunny", cost=1)
        eg.add_tool("calendar", handler=lambda: "no events", cost=1)
        eg.add_tool("finish", handler=lambda: "done", cost=0)
        eg.add_dependency("start", "weather", 1)
        eg.add_dependency("weather", "calendar", 1)
        eg.add_dependency("calendar", "finish", 1)
        success, executed, res = eg.execute()
        assert success
        assert "weather" in executed

    def test_execute_with_failure(self):
        eg = ExecutionGraph()
        eg.set_start("start")
        eg.set_goal("finish")
        eg.add_tool("weather", handler=lambda: (_ for _ in ()).throw(Exception("API down")), cost=1)
        eg.add_tool("finish", handler=lambda: "done", cost=0)
        eg.add_dependency("start", "weather", 1)
        eg.add_dependency("weather", "finish", 1)
        success, executed, res = eg.execute()
        assert not success

    def test_stats(self, exe_graph):
        stats = exe_graph.stats()
        assert "nodes" in stats
        assert "edges" in stats
