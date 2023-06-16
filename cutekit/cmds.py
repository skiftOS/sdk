import os
import logging
import requests
import sys

from typing import Callable, cast, Optional, NoReturn

from cutekit import context, shell, const, vt100, builder, graph, project
from cutekit.args import Args
from cutekit.jexpr import Json
from cutekit.model import Extern
from cutekit.context import contextFor

Callback = Callable[[Args], None]

logger = logging.getLogger(__name__)


class Cmd:
    shortName: Optional[str]
    longName: str
    helpText: str
    callback: Callable[[Args], NoReturn]
    isPlugin: bool = False

    def __init__(self, shortName: Optional[str], longName: str, helpText: str, callback: Callable[[Args], NoReturn]):
        self.shortName = shortName
        self.longName = longName
        self.helpText = helpText
        self.callback = callback


cmds: list[Cmd] = []


def append(cmd: Cmd):
    cmd.isPlugin = True
    cmds.append(cmd)
    cmds.sort(key=lambda c: c.shortName or c.longName)


def runCmd(args: Args):
    project.chdir()

    targetSpec = cast(str, args.consumeOpt(
        "target", "host-" + shell.uname().machine))

    componentSpec = args.consumeArg()

    if componentSpec is None:
        raise RuntimeError("Component not specified")

    component = builder.build(componentSpec, targetSpec)

    os.environ["CK_TARGET"] = component.context.target.id
    os.environ["CK_COMPONENT"] = component.id()
    os.environ["CK_BUILDDIR"] = component.context.builddir()

    shell.exec(component.outfile(), *args.args)


cmds += [Cmd("r", "run", "Run the target", runCmd)]


def testCmd(args: Args):
    project.chdir()

    targetSpec = cast(str, args.consumeOpt(
        "target", "host-" + shell.uname().machine))
    builder.testAll(targetSpec)


cmds += [Cmd("t", "test", "Run all test targets", testCmd)]


def debugCmd(args: Args):
    project.chdir()

    targetSpec = cast(str, args.consumeOpt(
        "target", "host-" + shell.uname().machine))

    componentSpec = args.consumeArg()

    if componentSpec is None:
        raise RuntimeError("Component not specified")

    component = builder.build(componentSpec, targetSpec)

    os.environ["CK_TARGET"] = component.context.target.id
    os.environ["CK_COMPONENT"] = component.id()
    os.environ["CK_BUILDDIR"] = component.context.builddir()

    shell.exec("lldb", "-o", "run", component.outfile(), *args.args)


cmds += [Cmd("d", "debug", "Debug the target", debugCmd)]


def buildCmd(args: Args):
    project.chdir()

    targetSpec = cast(str, args.consumeOpt(
        "target", "host-" + shell.uname().machine))

    componentSpec = args.consumeArg()

    if componentSpec is None:
        builder.buildAll(targetSpec)
    else:
        builder.build(componentSpec, targetSpec)


cmds += [Cmd("b", "build", "Build the target", buildCmd)]


def listCmd(args: Args):
    project.chdir()

    components = context.loadAllComponents()
    targets = context.loadAllTargets()

    vt100.title("Components")
    if len(components) == 0:
        print(f"   (No components available)")
    else:
        print(vt100.indent(vt100.wordwrap(
            ", ".join(map(lambda m: m.id, components)))))
    print()

    vt100.title("Targets")

    if len(targets) == 0:
        print(f"   (No targets available)")
    else:
        print(vt100.indent(vt100.wordwrap(", ".join(map(lambda m: m.id, targets)))))

    print()


cmds += [Cmd("l", "list", "List the targets", listCmd)]


def cleanCmd(args: Args):
    project.chdir()
    shell.rmrf(const.BUILD_DIR)


cmds += [Cmd("c", "clean", "Clean the build directory", cleanCmd)]


def nukeCmd(args: Args):
    project.chdir()
    shell.rmrf(const.PROJECT_CK_DIR)


cmds += [Cmd("n", "nuke", "Clean the build directory and cache", nukeCmd)]


def helpCmd(args: Args):
    usage()

    print()

    vt100.title("Description")
    print(f"    {const.DESCRIPTION}")

    print()
    vt100.title("Commands")
    for cmd in cmds:
        pluginText = ""
        if cmd.isPlugin:
            pluginText = f"{vt100.CYAN}(plugin){vt100.RESET}"

        print(
            f" {vt100.GREEN}{cmd.shortName or ' '}{vt100.RESET}  {cmd.longName} - {cmd.helpText} {pluginText}")

    print()
    vt100.title("Logging")
    print(f"    Logs are stored in:")
    print(f"     - {const.PROJECT_LOG_FILE}")
    print(f"     - {const.GLOBAL_LOG_FILE}")


cmds += [Cmd("h", "help", "Show this help message", helpCmd)]


def versionCmd(args: Args):
    print(f"CuteKit v{const.VERSION_STR}\n")


cmds += [Cmd("v", "version", "Show current version", versionCmd)]


def graphCmd(args: Args):
    project.chdir()

    targetSpec = cast(str, args.consumeOpt(
        "target", "host-" + shell.uname().machine))

    scope: Optional[str] = cast(Optional[str], args.tryConsumeOpt("scope"))
    onlyLibs: bool = args.consumeOpt("only-libs", False) == True
    showDisabled: bool = args.consumeOpt("show-disabled", False) == True

    context = contextFor(targetSpec)

    graph.view(context, scope=scope, showExe=not onlyLibs,
               showDisabled=showDisabled)


cmds += [Cmd("g", "graph", "Show dependency graph", graphCmd)]


def grabExtern(extern: dict[str, Extern]):
    for extSpec, ext in extern.items():
        extPath = os.path.join(const.EXTERN_DIR, extSpec)

        if os.path.exists(extPath):
            print(f"Skipping {extSpec}, already installed")
            continue

        print(f"Installing {extSpec}-{ext.tag} from {ext.git}...")
        shell.popen("git", "clone", "--depth", "1", "--branch",
                    ext.tag, ext.git, extPath)

        if os.path.exists(os.path.join(extPath, "project.json")):
            grabExtern(context.loadProject(extPath).extern)


def installCmd(args: Args):
    project.chdir()

    pj = context.loadProject(".")
    grabExtern(pj.extern)


cmds += [Cmd("i", "install", "Install all the external packages", installCmd)]


def initCmd(args: Args):
    repo = args.consumeOpt('repo', const.DEFAULT_REPO_TEMPLATES)
    list = args.consumeOpt('list')

    template = args.consumeArg()
    name = args.consumeArg()

    logger.info("Fetching registry...")
    r = requests.get(
        f'https://raw.githubusercontent.com/{repo}/main/registry.json')

    if r.status_code != 200:
        logger.error('Failed to fetch registry')
        exit(1)

    registry = r.json()

    if list:
        print('\n'.join(
            f"* {entry['id']} - {entry['description']}" for entry in registry))
        return

    if not template:
        raise RuntimeError('Template not specified')

    template_match: Callable[[Json], str] = lambda t: t['id'] == template
    if not any(filter(template_match, registry)):
        raise LookupError(f"Couldn't find a template named {template}")

    if not name:
        logger.info(f"No name was provided, defaulting to {template}")
        name = template

    if os.path.exists(name):
        raise RuntimeError(f"Directory {name} already exists")

    print(f"Creating project {name} from template {template}...")
    shell.cloneDir(f"https://github.com/{repo}", template, name)
    print(f"Project {name} created\n")

    print("We suggest that you begin by typing:")
    print(f"  {vt100.GREEN}cd {name}{vt100.RESET}")
    print(f"  {vt100.GREEN}cutekit install{vt100.BRIGHT_BLACK} # Install external packages{vt100.RESET}")
    print(
        f"  {vt100.GREEN}cutekit build{vt100.BRIGHT_BLACK}  # Build the project{vt100.RESET}")


cmds += [Cmd("I", "init", "Initialize a new project", initCmd)]


def usage():
    print(f"Usage: {const.ARGV0} <command> [args...]")


def error(msg: str) -> None:
    print(f"{vt100.RED}Error:{vt100.RESET} {msg}\n", file=sys.stderr)


def exec(args: Args):
    cmd = args.consumeArg()

    if cmd is None:
        raise RuntimeError("No command specified")

    for c in cmds:
        if c.shortName == cmd or c.longName == cmd:
            c.callback(args)
            return

    raise RuntimeError(f"Unknown command {cmd}")