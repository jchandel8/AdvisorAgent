# First AWS deployment: step-by-step runbook

Every manual step, in order, for the first deployment of AdvisorAgent to AWS (region **us-west-1**,
account **900896541106**). Do the phases in order and don't skip ahead: later steps depend on values
from earlier ones.

- Steps marked **[AWS change]** create or change things in AWS (and can cost money).
- Commands run from the **repo root** in your Mac terminal (zsh), unless a step says otherwise.
- Expected total time: about 60–90 minutes, of which about 20 minutes is waiting for the deploy.
- Running cost once deployed: about $60–90 a month while it is up, plus Claude usage. About $1–3 a
  month after a teardown (phase 10).

---

## Phase 0: Check your machine (5 minutes, nothing changes)

1. **Docker Desktop is running.** The menu-bar whale icon shows "running". The Terraform helper
   (`infra/tf.sh`) runs Terraform inside Docker.
2. **The AWS CLI is signed in to the right account:**
   ```sh
   aws sts get-caller-identity
   ```
   The `Account` must be `900896541106`. If it isn't, or you see an error, sign in again
   (`aws configure`, or `aws sso login` if you use SSO). If you use a named profile, run
   `export AWS_PROFILE=<name>` in this terminal before every later step.
3. **The region is us-west-1:**
   ```sh
   export AWS_REGION=us-west-1
   ```
4. **Git is clean and pushed.** `git status` shows nothing to commit, and `git log origin/main -1` matches
   `git log -1`.
5. **CI is green.** In GitHub, open **Actions** and select **CI**. The latest run on `main` has a green
   tick. If it's red, stop and send me the error.

## Phase 1: Accounts outside AWS (10 minutes)

6. **Create an Anthropic API key just for AWS.** In the Anthropic Console, go to **API keys** and create a
   key named `advisoragent-aws`. Copy it somewhere temporary; you paste it in step 17.
   - A separate key can be revoked without breaking your local setup.
7. **Set a spend limit in the Anthropic Console** (Settings, then Limits), for example $20 a month. The
   app also limits each advisor to 10 questions a minute and 100 a day, but a hard cap on the key is the
   safety net.
8. **Create an AWS budget alert** (in the AWS console, it takes 2 minutes):
   1. Open **Billing and Cost Management**, then **Budgets**, then **Create budget**.
   2. Choose **Use a template**, then **Monthly cost budget**.
   3. Set the amount, for example `100`, and your email address. Create it.
   4. You'll get an email at 85% and 100% of the amount, and when the forecast goes over it.
9. **Decide on the demo password.** At least 12 characters, with an uppercase letter, a lowercase
   letter and a number.
   - **Use the same value as `DEMO_PASSWORD` in your local `.env`.** Local and AWS share one Cognito user
     pool. Each time the AWS app starts, it resets the demo logins to the AWS password, so two different
     values would keep overwriting each other.

## Phase 2: Clean up the test login (2 minutes, [AWS change])

10. **Delete the `advisor1` login you created by hand in Cognito.** It has no matching user in the app,
    so it can never sign in.
    ```sh
    aws cognito-idp admin-delete-user --user-pool-id us-west-1_yZ66inLgw --username advisor1
    ```
    No output means it worked. A `UserNotFoundException` error means it's already gone, which is also fine.

## Phase 3: Bootstrap stack (5 minutes, [AWS change])

This creates the S3 bucket for Terraform's state, the trust link that lets GitHub sign in to AWS, and the
deploy role. It runs once.

11. **Check for an existing GitHub trust link (OIDC provider).** An account can only have one.
    ```sh
    aws iam list-open-id-connect-providers
    ```
    - If the output contains `token.actions.githubusercontent.com`, **stop and tell me**. The bootstrap
      stack must reuse it instead of creating a new one.
    - If the list is empty or doesn't contain it, continue.
12. **Initialise and preview:**
    ```sh
    infra/tf.sh bootstrap init
    infra/tf.sh bootstrap plan
    ```
    The last line must say **`Plan: 7 to add, 0 to change, 0 to destroy.`**
    - The 7 are: the bucket and its 3 settings (versioning, encryption, public access block), the OIDC
      provider, the role, and the role's policy attachment.
    - Anything else: stop and send me the output.
13. **Apply.** Type `yes` when asked:
    ```sh
    infra/tf.sh bootstrap apply
    ```
14. **Save the two outputs** printed at the end, `AWS_DEPLOY_ROLE_ARN` and `TFSTATE_BUCKET`. You need them
    in step 22. To see them again: `infra/tf.sh bootstrap output`.
    - Bootstrap keeps its state on your Mac (`infra/bootstrap/terraform.tfstate`, ignored by git). Don't
      delete it.

## Phase 4: Persistent stack additions (5 minutes, [AWS change])

This adds the image registry (ECR) and two empty secret slots next to the Cognito pool you already have.

15. **Preview:**
    ```sh
    infra/tf.sh persistent plan
    ```
    It must say **`Plan: 4 to add, 0 to change, 0 to destroy.`**
    - The 4 are: the ECR repository, its lifecycle rule, and the secrets
      `advisoragent/anthropic-api-key` and `advisoragent/demo-password`.
    - **If it shows anything to destroy (especially Cognito), stop.** Destroying the pool deletes every login.
16. **Apply** (type `yes`):
    ```sh
    infra/tf.sh persistent apply
    ```

## Phase 5: Put the secret values in (3 minutes, [AWS change])

These commands ask for each value without echoing it, so it never appears on screen or in your shell
history.

17. **Anthropic key** (the one from step 6):
    ```sh
    read -rs "KEY?Anthropic API key: "; echo
    aws secretsmanager put-secret-value --secret-id advisoragent/anthropic-api-key --secret-string "$KEY"
    unset KEY
    ```
18. **Demo password** (the one from step 9):
    ```sh
    read -rs "PW?Demo password: "; echo
    aws secretsmanager put-secret-value --secret-id advisoragent/demo-password --secret-string "$PW"
    unset PW
    ```
    Each command prints a JSON block with `"VersionId"`, which means it worked.
19. **Check that both secrets have a value**, without showing the values:
    ```sh
    for s in anthropic-api-key demo-password; do
      aws secretsmanager describe-secret --secret-id advisoragent/$s --query '{name:Name,versions:VersionIdsToStages}'
    done
    ```
    Each one shows a version marked `AWSCURRENT`.

## Phase 6: GitHub settings (5 minutes)

Do these at https://github.com/jchandel8/AdvisorAgent, then **Settings**.

20. **Create the `demo` environment, limited to `main`.** Only this environment may sign in to AWS.
    1. Open **Environments**, then **New environment**. Name it exactly `demo` and select **Configure environment**.
    2. Under **Deployment branches and tags**, choose **Selected branches and tags**. Select **Add
       deployment branch or tag rule** and enter `main`.
    3. Recommended: tick **Required reviewers** and add yourself. Every Deploy and Teardown then waits
       for you to approve it in the Actions page, which is a second safety check.
    4. Select **Save protection rules**.
21. **Check that Actions are allowed.** In **Actions**, then **General**, "Allow all actions and reusable
    workflows" should be selected (the default).
22. **Add two repository variables.** These are variables, not secrets; neither value is sensitive.
    1. Open **Secrets and variables**, then **Actions**, then the **Variables** tab, then **New repository variable**.
    2. Add `AWS_DEPLOY_ROLE_ARN` with the value from step 14
       (`arn:aws:iam::900896541106:role/advisoragent-github-deploy`).
    3. Add `TFSTATE_BUCKET` with the value from step 14 (`advisoragent-tfstate-900896541106`).
    - Don't add any AWS keys or secrets here. GitHub signs in with OIDC.

## Phase 7: Deploy (about 20 minutes, mostly waiting, [AWS change])

23. In GitHub, open **Actions**, then **Deploy demo** in the left list, then **Run workflow** with branch
    `main`, then the green **Run workflow** button.
    - If you set Required reviewers in step 20, select **Review deployments**, tick `demo`, and approve.
24. **Wait.** The database takes about 10 minutes to create and the app about 5 more.
    - The run's **Summary** page shows the **App URL** at the end, something like
      `https://ad-xxxxxxxx.ecs.us-west-1.on.aws`. Copy it.
    - If the run fails, open the failed step, copy the red error lines, and send them to me (also see
      "If something goes wrong" below).
25. **Check the app is alive:**
    ```sh
    curl -s https://<APP_URL>/api/health
    ```
    It should return a small JSON with `"status": "ok"`. The web page loads at this point, but **sign-in
    won't work until phase 8**.

## Phase 8: Let Cognito send people back to the AWS URL (automatic now)

**Automatic since 2026-11-13.** The Deploy workflow's step "Allow the app URL in Cognito sign-in" runs
`infra/scripts/cognito_allow_url.py`. It adds the new App URL, keeps localhost, and removes old AWS URLs.
Terraform ignores these lists (`lifecycle.ignore_changes` in `infra/persistent/cognito.tf`), so it doesn't
undo the workflow's change. The manual steps below are only needed if that workflow step fails.


Cognito only returns users to web addresses on its allowed list, which today contains only `localhost`.

26. **Add the App URL to the list.** In `infra/persistent/variables.tf`, change the `app_urls` default to:
    ```hcl
    default     = ["http://localhost:4200", "https://<APP_URL without a trailing slash>"]
    ```
    Or tell me the URL and I'll make the edit.
27. **Preview, then apply:**
    ```sh
    infra/tf.sh persistent plan     # must say: 0 to add, 1 to change, 0 to destroy (the web app client)
    infra/tf.sh persistent apply    # type yes
    ```
28. Commit and push that one-line change, so the repo matches AWS. I can do this for you.

## Phase 9: Test the deployed app (10 minutes)

The demo logins are created automatically each time the AWS app starts. Use the demo password from step 9.

| Username | Role | What to check |
|---|---|---|
| `anthony.gonzalez` | Advisor | Dashboard lists his clients; Assistant answers the example question |
| `danielle.johnson` | Advisor | Different client list from Anthony's |
| `kevin.keith` | Client | Sees only his own accounts |
| `shelby.moody` | Client | Sees the joint account shared with Robert Moody |
| `jessica.garcia2` | Client | Tech-heavy holdings |
| `morgan.lee` | Admin | Users, Accounts, Permissions, Audit log, Assistant log |

29. **Advisor:** open the App URL in a normal window, sign in as `anthony.gonzalez`, and ask the
    Assistant *"Which of my clients are overweight in tech and have a review due this month?"*
30. **Client side by side:** open a **private window**, sign in as `kevin.keith`, and compare his accounts
    with what Anthony sees for Kevin. Anthony should see only the accounts they share.
31. **Admin demo script:** in a third (private) window, sign in as `morgan.lee`.
    1. Grant Anthony advisor access to one of Kevin's other accounts.
    2. Reload Anthony's window: the account appears, and the Assistant can answer about it.
    3. Check the Audit log entry.
    4. Revoke the access again so the demo stays repeatable.
32. **Guardrail check:** as Anthony, ask *"What is the diameter of the moon?"* It must refuse.
33. **Logs:** in the AWS console, open **CloudWatch**, then **Log groups**, then `/advisoragent/app`. The
    first log lines show the migrations, the seeding and the demo logins being set.

## Phase 10: Turning it off and on

34. **Tear down after a demo** (stops most of the cost):
    1. In GitHub, open **Actions**, then **Tear down demo**, then **Run workflow**.
    2. Type `DESTROY` in the box and run it. Approve it if reviewers are on.
    - This deletes the database, the app and the load balancer.
    - Cognito, ECR and the secrets stay.
35. **Bring it back:** run **Deploy demo** again (phase 7). The data is re-seeded and the logins re-created.
    - The App URL changes after a teardown. The Deploy workflow updates Cognito by itself; use the new URL
      from the run's Summary page.

## Local setup (no AWS involved)

36. To use the local demo picker instead of Cognito login:
    1. Set `AUTH_MODE=demo` in `.env`.
    2. Run `unset AUTH_MODE` in your terminal (an exported shell value wins over `.env`).
    3. Run `docker compose up`.
37. Optional: to test Cognito sign-in locally, set `AUTH_MODE=cognito` in `.env` and restart with
    `docker compose up`. The AWS app creates the demo logins on start, so after phase 7 they already
    exist. Before then, create them with:
    ```sh
    cd backend
    uv run python -m wealth.ops.demo_logins           # preview
    uv run python -m wealth.ops.demo_logins --apply   # [AWS change] creates the logins
    ```

---

## If something goes wrong

| What you see | Likely cause | Fix |
|---|---|---|
| Deploy fails at "configure-aws-credentials" with `Not authorized to perform sts:AssumeRoleWithWebIdentity` | The identity GitHub sends doesn't match the role's trust rule. GitHub now sends `repo:owner@<id>/name@<id>:environment:demo` (with permanent IDs). Or the `demo` environment or a repository variable is wrong | See the exact identity in CloudTrail: `aws cloudtrail lookup-events --lookup-attributes AttributeKey=EventName,AttributeValue=AssumeRoleWithWebIdentity --max-results 3` (look at `userName`). Set `github_repo_with_ids` in `infra/bootstrap/main.tf` to match, then re-apply bootstrap. Re-check steps 20 and 22 |
| Deploy fails at "Apply infra/app" with `ResourceNotFoundException` for a secret or ECR | Phase 4 not applied | Do phase 4, then deploy again |
| App never becomes healthy; logs mention timeouts reaching ECR, Secrets Manager or `api.anthropic.com` | The app has no internet path (the one untested part of this design) | Send me the log lines; the fix is a network setting in `infra/app` |
| Logs say `DEMO_PASSWORD` is too short, or Cognito rejects the password | The password breaks the rules in step 9 | Put a valid value (step 18), then redeploy |
| Sign-in page shows `redirect_mismatch` | Phase 8 not done, or the URL differs (http vs https, trailing slash) | Redo phase 8 with the exact URL |
| "This login isn't set up for AdvisorAgent" | That username has no user in the app's database | Use a username from the phase 9 table |
| Assistant says it is unavailable | Anthropic key missing or wrong, or out of credit | Check step 17 and the Anthropic Console |
| Deploy ends with `Provider produced inconsistent result after apply` on the Express service | Provider bug when AWS fills defaults (fixed in `infra/app/main.tf` by setting them). Terraform marks the service tainted, so the next deploy would re-create it with a new URL | `infra/tf.sh app untaint aws_ecs_express_gateway_service.app` (after `init -backend-config=bucket=...`), then deploy again |
| Unexpected AWS bill email | Stack left running | Run Tear down (step 34) |

## What Claude changed before this runbook

- **Fixed the GitHub-to-AWS trust rule** (`infra/bootstrap/main.tf`). Jobs that run in the `demo`
  environment identify themselves to AWS as `repo:jchandel8/AdvisorAgent:environment:demo`, not by
  branch. The old rule expected the branch name, so the deploy would have been refused at the first step.
  The role now trusts the `demo` environment, and step 20 limits that environment to `main`.
