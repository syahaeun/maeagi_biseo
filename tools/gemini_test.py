"""Gemini smoke test using real .env credentials and the Google API only."""
import argparse
import sys
from maeagi_biseo.llm.client import generate_reply, list_models, choose_chat_model, ApiError
from maeagi_biseo.llm.settings import provider_defaults, key_with_source
from maeagi_biseo.resources import DEFAULTS, PERSONAS, tr


def run_check(config, key, model=None, list_only=False):
    models = list_models(config, key)
    print(tr('cli.models_count', count=len(models)))
    if list_only:
        for name in models:
            print(name)
        return
    selected = model or config.get('model')
    if not selected:
        selected = choose_chat_model(models)
    config['model'] = selected
    print(tr('cli.selected_model', model=selected))
    messages = [{'role': 'user', 'content': tr('settings.test_prompt')}]
    answer = generate_reply(config, key, messages, PERSONAS['prompt_template'].format(**DEFAULTS))
    print(tr('settings.test_success', answer=answer))
    messages.extend([{'role': 'assistant', 'content': answer}, {'role': 'user', 'content': tr('cli.followup_prompt')}])
    followup = generate_reply(config, key, messages, PERSONAS['prompt_template'].format(**DEFAULTS))
    print(tr('cli.followup_success', answer=followup))


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    parser = argparse.ArgumentParser(description=tr('cli.gemini_description'))
    parser.add_argument('--live', action='store_true', help=tr('cli.live_help'))
    parser.add_argument('--list-models', action='store_true', help=tr('cli.list_help'))
    parser.add_argument('--model', help=tr('settings.model_placeholder'))
    args = parser.parse_args()
    config = provider_defaults('gemini')
    try:
        key, source = key_with_source('gemini')
        if not key:
            raise ApiError(tr('api.key_required'))
        print(tr('cli.live_mode', source=source))
        run_check(config, key, args.model, args.list_models)
        return 0
    except ApiError as exc:
        print(tr('settings.test_failure', error=str(exc)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
