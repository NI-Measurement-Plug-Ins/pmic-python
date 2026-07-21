from nidcpower import Session

def build_trigger_terminal(resource_name: str, channel_name: str, event_name: str) -> str:
    return f'/{resource_name}/Engine{channel_name}/{event_name}'
