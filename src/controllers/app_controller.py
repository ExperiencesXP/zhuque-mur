from commands.core import Commands
from views.cli import CLI


class AppController:
    def __init__(self):
        self.view = CLI()
        self.commands = Commands(self)
        self.running = True

    def run(self):
        self.view.welcome()
        self.view.warning()
        while self.running:
            command = self.view.get_input()
            self.route(command)

    def route(self, raw):
        if raw is None or not str(raw).strip():
            return
        verb, _, rest = str(raw).strip().partition(" ")
        output = self.handle(verb.lower(), rest.strip() or None)
        if output is not None:
            if isinstance(output, (list, tuple)):
                self.view.display(*output)
            else:
                self.view.display(output)

    def handle(self, command, arg=None):
        match command:
            case "exit" | "quit":
                self.running = False
                return "Goodbye."
            case "help":
                return self.commands.help()
            case "status":
                return self.commands.status()
            case "target":
                return self.commands.target(arg)
            case "untarget":
                return self.commands.untarget()
            case "inspect" | "license":
                return self.commands.inspect()
            case "fetch":
                return self.commands.fetch()
            case "analyze":
                return self.commands.analyze()
            case "specify":
                return self.commands.specify()
            case "implement":
                return self.commands.implement()
            case "continue" | "resume":
                return self.commands.continue_session(arg)
            case "run":
                return self.commands.run_pipeline()
            case "model":
                return self.commands.model(arg)
            case "auth" | "connect" | "login":
                return self.commands.auth(arg)
            case "rooms":
                return self.commands.rooms(arg)
            case "clear":
                return self.commands.clear(arg)
            case _:
                return self.commands.unknown(command)
