# Static PWA: private S3 bucket behind CloudFront (OAC). One URL for phone and desktop (001 R11).

resource "aws_s3_bucket" "web" {
  bucket        = local.web_bucket
  force_destroy = true # contents are generated from frontend/ and can always be re-uploaded
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "web" {
  name                              = "${var.project}-web"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

locals {
  # The API host is a region wildcard: the API's CORS already references CloudFront, so naming the exact
  # API endpoint here would create a dependency cycle.
  s3_post_origins = "https://${local.data_bucket}.s3.amazonaws.com https://${local.data_bucket}.s3.${var.region}.amazonaws.com"
  csp = join("; ", [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    "font-src 'self'",
    "manifest-src 'self'",
    "worker-src 'self'",
    "connect-src 'self' https://*.execute-api.${var.region}.amazonaws.com https://cognito-idp.${var.region}.amazonaws.com ${local.s3_post_origins}",
    "media-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ])
}

resource "aws_cloudfront_response_headers_policy" "web" {
  name = "${var.project}-headers"

  security_headers_config {
    content_security_policy {
      content_security_policy = local.csp
      override                = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      override                   = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "no-referrer"
      override        = true
    }
  }

  custom_headers_config {
    items {
      header   = "Permissions-Policy"
      value    = "microphone=(self), camera=(), geolocation=()"
      override = true
    }
  }
}

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

resource "aws_cloudfront_distribution" "web" {
  enabled             = true
  comment             = var.project
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  http_version        = "http2and3"

  origin {
    origin_id                = "web"
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }

  default_cache_behavior {
    target_origin_id           = "web"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.optimized.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.web.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

data "aws_iam_policy_document" "web_bucket" {
  statement {
    sid       = "CloudFrontRead"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.web.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.web.arn]
    }
  }
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.web.arn, "${aws_s3_bucket.web.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "web" {
  bucket     = aws_s3_bucket.web.id
  policy     = data.aws_iam_policy_document.web_bucket.json
  depends_on = [aws_s3_bucket_public_access_block.web]
}

# --- Files -----------------------------------------------------------------------------------------

locals {
  frontend_dir = "${path.module}/../frontend"
  frontend_files = [
    for f in fileset(local.frontend_dir, "**") : f
    if !startswith(f, "tests/") && f != "config.js" && f != "config.example.js" && !endswith(f, ".DS_Store")
  ]
  mime = {
    html        = "text/html; charset=utf-8"
    css         = "text/css; charset=utf-8"
    js          = "text/javascript; charset=utf-8"
    webmanifest = "application/manifest+json"
    png         = "image/png"
    svg         = "image/svg+xml"
    ico         = "image/x-icon"
    json        = "application/json"
  }
}

resource "aws_s3_object" "frontend" {
  for_each      = toset(local.frontend_files)
  bucket        = aws_s3_bucket.web.id
  key           = each.value
  source        = "${local.frontend_dir}/${each.value}"
  etag          = filemd5("${local.frontend_dir}/${each.value}")
  content_type  = lookup(local.mime, reverse(split(".", each.value))[0], "application/octet-stream")
  cache_control = "no-cache"
}

resource "aws_s3_object" "config_js" {
  bucket        = aws_s3_bucket.web.id
  key           = "config.js"
  content_type  = "text/javascript; charset=utf-8"
  cache_control = "no-cache"
  content = <<-EOT
    // Generated by Terraform. Do not edit.
    window.APP_CONFIG = ${jsonencode({
  region           = var.region
  userPoolClientId = aws_cognito_user_pool_client.web.id
  apiUrl           = aws_apigatewayv2_api.http.api_endpoint
})};
  EOT
}
