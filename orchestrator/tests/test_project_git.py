import subprocess

from coding import project_git


def _repo(path):
    path.mkdir()
    for args in (["init", "-q", "-b", "main"], ["config", "user.name", "Ana"], ["config", "user.email", "s@x"]):
        subprocess.run(["git", "-C", str(path), *args], check=True)
    (path / "app.py").write_text("print(1)\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "inicio"], check=True)
    return path


def _git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout.strip()


def test_each_task_gets_its_branch_and_a_commit_without_touching_main(tmp_path):
    repo = _repo(tmp_path / "proyecto")
    branch = project_git.start_branch(repo, "Arregla el botón de sumar")
    assert branch.startswith("chati/arregla-el-boton-de-sumar-") and _git(repo, "branch", "--show-current") == branch
    assert project_git.start_branch(repo, "otra cosa") == branch
    assert project_git.commit(repo, branch, "Arregla el botón de sumar") is None
    (repo / "app.py").write_text("print(2)\n", encoding="utf-8")
    sha = project_git.commit(repo, branch, "Arregla el botón de sumar")
    assert sha and _git(repo, "log", "-1", "--format=%s") == "Chati: Arregla el botón de sumar"
    assert _git(repo, "log", "-1", "--format=%s", "main") == "inicio"


def test_dirty_repos_and_plain_folders_are_left_alone(tmp_path):
    repo = _repo(tmp_path / "proyecto")
    (repo / "app.py").write_text("a medias\n", encoding="utf-8")
    assert project_git.start_branch(repo, "x") is None and _git(repo, "branch", "--show-current") == "main"
    plain = tmp_path / "carpeta"
    plain.mkdir()
    assert project_git.start_branch(plain, "x") is None
    assert project_git.commit(repo, "chati/otra", "x") is None and _git(repo, "status", "--porcelain")
