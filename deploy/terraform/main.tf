locals {
  compose_filename = "docker-compose.${var.environment_name}.yml"
  # minio-init is deliberately excluded: it's a one-shot container (mc bucket
  # setup) that exits 0 on success, but `docker compose up --wait` treats any
  # explicitly-targeted service transitioning to "exited" as a wait failure,
  # regardless of exit code (observed directly in a staging deploy run). It
  # still runs correctly on its own: api/worker declare
  # `depends_on: minio-init: condition: service_completed_successfully`,
  # which Compose enforces via normal dependency resolution (unrelated to
  # `--wait`) the moment the migration step below starts the api container.
  # Per environment: production compose has no neo4j service, so the default
  # omits it; staging appends neo4j through TF_VAR_infra_services.
  infra_services = var.infra_services
  # The remote backup gate runs in the release workflow
  # (deploy/scripts/check_remote_backups.sh) before Terraform starts, so it is
  # no longer repeated here.
  deploy_env_content = <<-EOT
${var.env_file_content}
RUDIX_API_IMAGE=${var.api_image}
RUDIX_WORKER_IMAGE=${var.worker_image}
RUDIX_FRONTEND_IMAGE=${var.frontend_image}
NEO4J_USERNAME=${var.neo4j_username}
NEO4J_PASSWORD=${var.neo4j_password}
EOT
  # Kept out of deploy_env_content deliberately: that file is written
  # persistently to the host and consumed by every service on every
  # container start, but the bootstrap credentials are only needed once, for
  # the single one-off `docker compose run` below. Written to its own file
  # (never shell-interpolated) so an admin password containing quotes or
  # other shell-special characters can't break the remote script, then
  # removed immediately after use.
  bootstrap_env_content = <<-EOT
BOOTSTRAP_ADMIN_EMAIL=${var.bootstrap_admin_email}
BOOTSTRAP_ADMIN_PASSWORD=${var.bootstrap_admin_password}
EOT
}

resource "null_resource" "compose_rollout" {
  triggers = {
    environment_name = var.environment_name
    ssh_host         = var.ssh_host
    app_path         = var.app_path
    compose_sha      = filesha256(var.compose_file_path)
    env_sha          = sha256(var.env_file_content)
    api_image        = var.api_image
    worker_image     = var.worker_image
    frontend_image   = var.frontend_image
    migration_cmd    = var.migration_command
    # Kept (now informational only) so existing state does not churn.
    backup_check = tostring(var.backup_check_enabled)
  }

  # Host key pinned: var.ssh_host_key is "<type> <base64>" (fields 2 and 3 of the
  # host's known_hosts line). With remote state an unchanged redeploy is a no-op;
  # `terraform apply -replace=null_resource.compose_rollout` forces a rollout.
  connection {
    type        = "ssh"
    host        = var.ssh_host
    port        = var.ssh_port
    user        = var.ssh_user
    private_key = var.ssh_private_key
    host_key    = var.ssh_host_key
    timeout     = "3m"
  }

  provisioner "remote-exec" {
    inline = [
      "mkdir -p '${var.app_path}'",
    ]
  }

  provisioner "file" {
    source      = var.compose_file_path
    destination = "${var.app_path}/${local.compose_filename}"
  }

  provisioner "file" {
    content     = local.deploy_env_content
    destination = "${var.app_path}/.env"
  }

  provisioner "file" {
    content     = var.registry_password
    destination = "${var.app_path}/.registry_password"
  }

  provisioner "file" {
    content     = local.bootstrap_env_content
    destination = "${var.app_path}/.bootstrap_admin_env"
  }

  provisioner "remote-exec" {
    inline = [
      "set -eu",
      "cd '${var.app_path}'",
      "cat .registry_password | docker login -u '${var.registry_user}' --password-stdin '${var.registry}'",
      "rm -f .registry_password",
      "docker image prune -f",
      "docker compose -f '${local.compose_filename}' pull",
      "docker compose -f '${local.compose_filename}' up -d --wait ${local.infra_services}",
      "docker compose -f '${local.compose_filename}' run --rm api ${var.migration_command}",
      # Idempotent: bootstrap_admin.py no-ops unless the database has zero
      # organizations, so this is safe to run on every deploy. `docker compose
      # run`'s file-based env flag isn't universally available across Compose
      # versions (--env-file vs --env-from-file, and older CLIs have neither),
      # so instead parse the file as plain KEY=value data (never as shell
      # code — `.`/source would mis-parse a password containing quotes or
      # other shell-special characters) and forward each var by name only
      # (`-e VAR`, no `=value`) so Compose reads it from the shell rather than
      # the command line.
      "while IFS='=' read -r key value; do [ -n \"$key\" ] && export \"$key=$value\"; done < .bootstrap_admin_env",
      "docker compose -f '${local.compose_filename}' run --rm -e BOOTSTRAP_ADMIN_EMAIL -e BOOTSTRAP_ADMIN_PASSWORD api python scripts/bootstrap_admin.py",
      "rm -f .bootstrap_admin_env",
      "docker compose -f '${local.compose_filename}' up -d --wait",
      "docker image prune -f",
      "docker compose -f '${local.compose_filename}' exec -T api python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=5)\"",
      "docker compose -f '${local.compose_filename}' exec -T api python -c \"import urllib.request, sys; r=urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready', timeout=5); print(r.read().decode())\" || true",
    ]
  }
}

output "deployment_target" {
  value = {
    environment = var.environment_name
    host        = var.ssh_host
    app_path    = var.app_path
    compose     = local.compose_filename
  }
}
