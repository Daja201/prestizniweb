# How to use these 5 prompts

1. Give each `prompt_N_*.md` file to a different AI model (or one after another in fresh chats). Each file already contains the shared contract, so the five parts fit together. They can run in parallel.
2. Put every file from every answer into one folder using the exact paths the answers print (they follow the layout in section 3 of the contract).
3. `cp .env.example .env`, edit it, then `docker compose up --build`.
4. Run the tests: `docker compose run --rm web pytest`.
5. If something fails, give the AI that OWNS the failing file the error together with the contract. Owners are listed in section 3.
