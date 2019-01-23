import json
import os

from cumulusci.tasks.salesforce import Deploy


deploy_options = Deploy.task_options.copy()
deploy_options["path"][
    "description"
] = "The path to the parent directory containing the metadata bundles directories"


class DeployBundles(Deploy):
    task_options = deploy_options

    def _run_task(self):
        path = self.options["path"]
        pwd = os.getcwd()

        path = os.path.join(pwd, path)

        self.logger.info("Deploying all metadata bundles in path {}".format(path))

        if not os.path.isdir(path):
            self.logger.warning("Path {} not found, skipping".format(path))
            return

        for item in sorted(os.listdir(path)):
            item_path = os.path.join(path, item)
            if not os.path.isdir(item_path):
                continue

            self.logger.info(
                "Deploying bundle: {}/{}".format(self.options["path"], item)
            )

            self._deploy_bundle(item_path)

    def _deploy_bundle(self, path):
        api = self._get_api(path)
        return api()

    def freeze(self, step):
        path = self.options["path"]
        steps = []
        for i, item in enumerate(sorted(os.listdir(path)), 1):
            name = os.path.basename(item)
            task_config = {
                "options": {
                    "dependencies": [
                        {
                            "repo_owner": self.project_config.repo_owner,
                            "repo_name": self.project_config.repo_name,
                            "tag": self.project_config.repo_commit,
                            "subfolder": "/".join([path, item]),
                        }
                    ]
                }
            }
            steps.append(
                {
                    "name": "Deploy {}/{}".format(path, name),
                    "path": "{}.{}".format(step.path, name),
                    "step_num": "{}.{}".format(step.step_num, i),
                    "kind": "metadata",
                    "is_required": True,
                    "task_class": "cumulusci.tasks.salesforce.UpdateDependencies",
                    "task_config": json.dumps(task_config),
                }
            )
        return steps
