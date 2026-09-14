module "model" {
  source    = "../model"
  model_dir = "${path.module}/../../model"
}
