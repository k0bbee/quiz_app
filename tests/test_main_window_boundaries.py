import ast
from pathlib import Path


def test_main_window_does_not_wrap_result_flow_actions():
    source = Path("ui/main_window.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    main_window = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "MainWindow"
    )
    method_names = {
        node.name
        for node in main_window.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert method_names.isdisjoint(
        {
            "_result_flow_controller",
            "_on_quiz_finished",
            "_on_open_progress_record",
            "_on_retry_incorrect",
            "_on_retry_unsure",
            "_on_retry_review",
            "_retry_current_session",
            "_on_practice_incorrect",
            "_on_retry_all",
        }
    )


def test_main_window_does_not_wrap_generation_flow_actions():
    source = Path("ui/main_window.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    main_window = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "MainWindow"
    )
    method_names = {
        node.name
        for node in main_window.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert method_names.isdisjoint(
        {
            "_generation_controller",
            "_prepare_generation_dialog",
            "_on_ai_generate",
            "_on_generation_workspace_accepted",
            "_on_generation_workspace_rejected",
            "_configure_generation_dialog",
            "_save_generated_dialog",
            "_generation_draft",
            "_sync_generation_draft",
            "_delete_generation_draft",
            "_on_resume_generation_draft",
        }
    )
