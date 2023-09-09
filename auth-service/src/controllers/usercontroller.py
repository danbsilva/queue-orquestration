import json

from decouple import config as config_env
from threading import Thread

from flask import request, Response, jsonify
from flask_restful import Resource
from flask_paginate import Pagination
from marshmallow import ValidationError
from werkzeug.exceptions import UnsupportedMediaType

from src.extensions.flask_cache import cache
from src.logging import Logger
from src.services.kafkaservice import KafkaService
from src.models.usermodel import UserModel
from src.schemas import userschemas
from src import messages
from src.providers import token_provider
from src.providers import hash_provider
from src.docs import auth


__module_name__ = 'src.controllers.usercontroller'


# Function to get page args
def get_page_args():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', int(config_env('PER_PAGE')), type=int)
    offset = (page - 1) * per_page
    return page, per_page, offset


def validate_schema(schema, data):
    try:
        schema.load(data)
    except ValidationError as e:
        return e.messages


class UsersResource(Resource):
    @staticmethod
    @token_provider.verify_token
    @token_provider.admin_required
    def post(user_authenticated):
        try:
            try:
                new_user = request.get_json()
            except UnsupportedMediaType as e:
                Logger().dispatch('INFO', __module_name__, 'UsersResource.post', str(e))
                return {'message': messages.UNSUPPORTED_MEDIA_TYPE}, 415
            except Exception as e:
                Logger().dispatch('INFO', __module_name__, 'UsersResource.post', str(e))
                return {'message': messages.BAD_REQUEST}, 400

            schema_validate = validate_schema(userschemas.UserPostSchema(), new_user)
            if schema_validate:
                Logger().dispatch('INFO', __module_name__, 'UsersResource.post',
                                       f'Schema validation error: {schema_validate}')
                return {'message': schema_validate}, 400

            if UserModel.get_by_email(email=new_user['email']):
                Logger().dispatch('INFO', __module_name__, 'UsersResource.post',
                                       f'Email {new_user["email"]} already exists')
                return {'message': messages.EMAIL_ALREADY_EXISTS}, 400

            try:
                user = UserModel.save(new_user)
                Logger().dispatch('INFO', __module_name__, 'UsersResource.post',
                                       f'User {user.uuid} created successfully by {user_authenticated["uuid"]}')
            except Exception as e:
                Logger().dispatch('CRITICAL', __module_name__, 'UsersResource.post',
                                        f'Error creating user: {str(e)}')
                return {'message': 'Error creating user'}, 400

            user_schema = userschemas.UserGetSchema()
            user_data = user_schema.dump(user)

            return {'user': user_data}, 201

        except Exception as e:
            Logger().dispatch('CRITICAL', __module_name__, 'UsersResource.post', str(e))
            return {'message': messages.INTERNAL_SERVER_ERROR}, 500

    @staticmethod
    @token_provider.verify_token
    @token_provider.admin_required
    @cache.cached(timeout=60, query_string=True)
    def get(user_authenticated):
        try:
            page, per_page, offset = get_page_args()

            users = UserModel.get_all()

            pagination_users = users[offset: offset + per_page]
            pagination = Pagination(page=page, per_page=per_page, total=len(users))

            users_schema = userschemas.UserGetSchema(many=True)
            users_data = users_schema.dump(users)

            Logger().dispatch('INFO', __module_name__, 'UsersResource.get',
                                   f'Returning {len(users_data)} users')
            return {'users': users_data,
                    'pagination': {
                        'total_pages': pagination.total_pages,
                        'current_page': page,
                        'per_page': pagination.per_page,
                        'total_items': pagination.total,
                        'has_next': pagination.has_next,
                        'has_prev': pagination.has_prev,
                        'total_items_this_page': len(pagination_users),
                        'offset': offset
                    }}, 200

        except Exception as e:
            Logger().dispatch('CRITICAL', __module_name__, 'UsersResource.get', str(e))
            return {'message': messages.INTERNAL_SERVER_ERROR}, 500


class UserResource(Resource):
    @staticmethod
    @token_provider.verify_token
    @token_provider.admin_required
    @cache.cached(timeout=60, query_string=True)
    def get(user_authenticated, user_uuid):
        try:
            user = UserModel.get_by_uuid(uuid=user_uuid)
            if not user:
                Logger().dispatch('INFO', __module_name__, 'UserResource.get',
                                       f'User {user_uuid} not found')
                return {'message': messages.USER_NOT_FOUND}, 404

            user_schema = userschemas.UserGetSchema()
            user_data = user_schema.dump(user)

            Logger().dispatch('INFO', __module_name__, 'UserResource.get',
                                   f'User {user_uuid} found')
            return {'user': user_data}, 200

        except Exception as e:
            Logger().dispatch('CRITICAL', __module_name__, 'UserResource.get', str(e))
            return {'message': messages.INTERNAL_SERVER_ERROR}, 500

    @staticmethod
    @token_provider.verify_token
    @token_provider.admin_required
    def patch(user_authenticated, user_uuid):
        try:
            try:
                data = request.get_json()
            except UnsupportedMediaType as e:
                Logger().dispatch('INFO', __module_name__, 'UserResource.patch', str(e))
                return {'message': messages.UNSUPPORTED_MEDIA_TYPE}, 415
            except Exception as e:
                Logger().dispatch('INFO', __module_name__, 'UserResource.patch', str(e))
                return {'message': messages.BAD_REQUEST}, 400

            schema_validate = validate_schema(userschemas.UserPatchSchema(), data)
            if schema_validate:
                Logger().dispatch('INFO', __module_name__, 'UserResource.patch',
                                       f'Schema validation error: {schema_validate}')
                return {'message': schema_validate}, 400

            if 'email' in data and UserModel.get_by_email(email=data['email']):
                return {'message': messages.EMAIL_ALREADY_EXISTS}, 400

            if 'username' in data and UserModel.get_by_username(username=data['username']):
                Logger().dispatch('INFO', __module_name__, 'UserResource.patch',
                                       f'User {user_uuid} already exists')
                return {'message': messages.USERNAME_ALREADY_EXISTS}, 400

            user = UserModel.get_by_uuid(uuid=user_uuid)

            if not user:
                Logger().dispatch('INFO', __module_name__, 'UserResource.patch',
                                       f'User {user_uuid} not found')
                return {'message': messages.USER_NOT_FOUND}, 404

            try:
                UserModel.update(user, data)
                Logger().dispatch('INFO', __module_name__, 'UserResource.patch',
                                       f'User {user_uuid} updated successfully by {user_authenticated["uuid"]}')
            except Exception as e:
                Logger().dispatch('CRITICAL', __module_name__, 'UserResource.patch',
                                        f'Error updating user: {str(e)}')
                return {'message': 'Error updating user'}, 400

            user_schema = userschemas.UserGetSchema()
            user_data = user_schema.dump(user)

            return {'user': user_data}, 200

        except Exception as e:
            Logger().dispatch('CRITICAL', __module_name__, 'UserResource.patch', str(e))
            return {'message': messages.INTERNAL_SERVER_ERROR}, 500

    @staticmethod
    @token_provider.verify_token
    @token_provider.admin_required
    def delete(user_authenticated, user_uuid):
        try:
            user = UserModel.get_by_uuid(uuid=user_uuid)
            if not user:
                Logger().dispatch('INFO', __module_name__, 'UserResource.delete',
                                       f'User {user_uuid} not found')
                return {'message': messages.USER_NOT_FOUND}, 404

            try:
                UserModel.delete(user)
                Logger().dispatch('INFO', __module_name__, 'UserResource.delete',
                                       f'User {user_uuid} deleted successfully by {user_authenticated["uuid"]}')
            except Exception as e:
                Logger().dispatch('CRITICAL', __module_name__, 'UserResource.delete', str(e))
                return {'message': messages.INTERNAL_SERVER_ERROR}, 500

            return {'message': messages.USER_DELETED_SUCCESSFULLY}, 200

        except Exception as e:
            Logger().dispatch('CRITICAL', __module_name__, 'UserResource.delete',
                                    f'Error deleting user: {str(e)}')
            return {'message': 'Error deleting user'}, 400


class UserMeResource(Resource):
    @staticmethod
    @token_provider.verify_token
    @cache.cached(timeout=60, query_string=True)
    def get(user_authenticated):
        try:
            user_schema = userschemas.UserGetSchema()
            user_data = user_schema.dump(user_authenticated)

            Logger().dispatch('INFO', __module_name__, 'UserMeResource.get',
                                   f'Returning user {user_authenticated["uuid"]}')
            return {'user': user_data}, 200

        except Exception as e:
            Logger().dispatch('CRITICAL', __module_name__, 'UserMeResource.get', str(e))
            return {'message': messages.INTERNAL_SERVER_ERROR}, 500

    @staticmethod
    @token_provider.verify_token
    def patch(user_authenticated):
        try:
            try:
                data = request.get_json()
            except UnsupportedMediaType as e:
                Logger().dispatch('INFO', __module_name__, 'UserMeResource.patch', str(e))
                return {'message': messages.UNSUPPORTED_MEDIA_TYPE}, 415
            except Exception as e:
                Logger().dispatch('INFO', __module_name__, 'UserMeResource.patch', str(e))
                return {'message': messages.BAD_REQUEST}, 400

            schema_validate = validate_schema(userschemas.UserPatchSchema(), data)
            if schema_validate:
                Logger().dispatch('INFO', __module_name__, 'UserMeResource.patch',
                                       f'Schema validation error: {schema_validate}')
                return {'message': schema_validate}, 400

            if 'email' in data and UserModel.get_by_email(email=data['email']):
                Logger().dispatch('INFO', __module_name__, 'UserMeResource.patch',
                                        f'Email {data["email"]} already exists')
                return {'message': messages.EMAIL_ALREADY_EXISTS}, 400

            if 'username' in data and UserModel.get_by_username(username=data['username']):
                Logger().dispatch('INFO', __module_name__, 'UserMeResource.patch',
                                       f'User {user_authenticated["uuid"]} already exists')
                return {'message': messages.USERNAME_ALREADY_EXISTS}, 400

            user = UserModel.get_by_uuid(uuid=user_authenticated['uuid'])

            if not user:
                Logger().dispatch('INFO', __module_name__, 'UserMeResource.patch',
                                       f'User {user_authenticated["uuid"]} not found')
                return {'message': messages.USER_NOT_FOUND}, 404

            try:
                UserModel.update(user, data)
                Logger().dispatch('INFO', __module_name__, 'UserMeResource.patch',
                                       f'User {user_authenticated["uuid"]} updated successfully')
            except Exception as e:
                Logger().dispatch('CRITICAL', __module_name__, 'UserMeResource.patch',
                                        f'Error updating user: {str(e)}')
                return {'message': 'Error updating user'}, 400

            user_schema = userschemas.UserGetSchema()
            user_data = user_schema.dump(user)

            return {'user': user_data}, 200

        except Exception as e:
            Logger().dispatch('CRITICAL', __module_name__, 'UserMeResource.patch', str(e))
            return {'message': messages.INTERNAL_SERVER_ERROR}, 500


class UserChangeRoleResource(Resource):
    @staticmethod
    @token_provider.verify_token
    @token_provider.admin_required
    def post(user_authenticated, user_uuid):
        try:

            user = UserModel.get_by_uuid(uuid=user_uuid)
            if not user:
                Logger().dispatch('INFO', __module_name__, 'UserChangeRoleResource.post',
                                       f'User {user_uuid} not found')
                return {'message': messages.USER_NOT_FOUND}, 404

            try:
                UserModel.change_role(user)
                Logger().dispatch('INFO', __module_name__, 'UserChangeRoleResource.post',
                                       f'Role of user {user_uuid} updated successfully by {user_authenticated["uuid"]}')
            except Exception as e:
                Logger().dispatch('CRITICAL', __module_name__, 'UserChangeRoleResource.post',
                                        f'Error updating role of user {user_uuid}: {str(e)}')
                return {'message': f'Error updating role of user {user_uuid}'}, 400


            user_schema = userschemas.UserGetSchema()
            user_data = user_schema.dump(user)

            return {'user': user_data}, 200

        except Exception as e:
            Logger().dispatch('CRITICAL', __module_name__, 'UserChangeRoleResource.post', str(e))
            return {'message': messages.INTERNAL_SERVER_ERROR}, 500


class UserMeChangePasswordResource(Resource):
    @staticmethod
    @token_provider.verify_token
    def patch(user_authenticated):
        try:
            try:
                data = request.get_json()
            except UnsupportedMediaType as e:
                Logger().dispatch('INFO', __module_name__, 'UserMeResource.patch', str(e))
                return {'message': messages.UNSUPPORTED_MEDIA_TYPE}, 415
            except Exception as e:
                Logger().dispatch('INFO', __module_name__, 'UserMeResource.patch', str(e))
                return {'message': messages.BAD_REQUEST}, 400

            schema_validate = validate_schema(userschemas.UserChangePasswordSchema(), data)

            if schema_validate:
                Logger().dispatch('INFO', __module_name__, 'UserMeResource.patch',
                                       f'Schema validation error: {schema_validate}')
                return {'message': schema_validate}, 400

            if data['new_password'] != data['confirm_new_password']:
                Logger().dispatch('INFO', __module_name__, 'UserMeResource.patch', 'Passwords not match')
                return {'message': messages.PASSWORDS_NOT_MATCH}, 400

            user = UserModel.get_by_uuid(uuid=user_authenticated['uuid'])
            if not hash_provider.check_password_hash(data['password'], user.password):
                Logger().dispatch('INFO', __module_name__, 'UserMeResource.patch', 'Actual password not match')
                return {'message': messages.ACTUAL_PASSWORD_NOT_MATCH}, 400

            try:
                UserModel.change_password(user, data['new_password'])
                Logger().dispatch('INFO', __module_name__, 'UserMeResource.patch',
                                       f'User {user_authenticated["uuid"]} changed password successfully')
            except Exception as e:
                Logger().dispatch('CRITICAL', __module_name__, 'UserMeResource.patch',
                                        f'Error changing password: {str(e)}')
                return {'message':'Error changing password'}, 400

            return {'message': messages.PASSWORD_CHANGED_SUCCESSFULLY}, 200

        except Exception as e:
            Logger().dispatch('CRITICAL', __module_name__, 'UserMeResource.patch', str(e))
            return {'message': messages.INTERNAL_SERVER_ERROR}, 500


class LoginResource(Resource):
    @staticmethod
    def post():
        try:
            try:
                user = request.get_json()
            except UnsupportedMediaType as e:
                Logger().dispatch('INFO', __module_name__, 'LoginResource.post', str(e))
                return {'message': messages.UNSUPPORTED_MEDIA_TYPE}, 415
            except Exception as e:
                Logger().dispatch('INFO', __module_name__, 'LoginResource.post', str(e))
                return {'message': messages.BAD_REQUEST}, 400

            schema_validate = validate_schema(userschemas.UserLoginSchema(), user)

            if schema_validate:
                Logger().dispatch('INFO', __module_name__, 'LoginResource.post',
                                       f'Schema validation error: {schema_validate}')
                return {'message': schema_validate}, 400

            user_db = UserModel.get_by_email(email=user['email'])

            if not user_db:
                Logger().dispatch('INFO', __module_name__, 'LoginResource.post',
                                       f'User {user["email"]} not found')
                return {'message': messages.INVALID_CREDENTIALS}, 401

            if not user_db.email_valid:
                Logger().dispatch('INFO', __module_name__, 'LoginResource.post',
                                       f'User {user["email"]} not validated')
                return {'message': messages.USER_NON_VALIDATED_EMAIL}, 400

            if not hash_provider.check_password_hash(user['password'], user_db.password):
                Logger().dispatch('INFO', __module_name__, 'LoginResource.post',
                                       f'User {user["email"]} invalid credentials')
                return {'message': messages.INVALID_CREDENTIALS}, 401

            try:
                token = token_provider.create_token(payload=user_db.to_json())
                Logger().dispatch('INFO', __module_name__, 'LoginResource.post',
                                       f'User {user["email"]} logged in successfully')
            except Exception as e:
                Logger().dispatch('CRITICAL', __module_name__, 'LoginResource.post',
                                        f'Error creating token: {str(e)}')
                return {'message': messages.ERROR_CREATING_TOKEN}, 401

            user_schema = userschemas.UserGetSchema()
            user_data = user_schema.dump(user_db)

            return {
                'token': f'Bearer {token}',
                'user': user_data
            }, 200

        except Exception as e:
            Logger().dispatch('CRITICAL', __module_name__, 'LoginResource.post', str(e))
            return {'message': messages.INTERNAL_SERVER_ERROR}, 500


class LogoutResource(Resource):
    @staticmethod
    @token_provider.verify_token
    def get(user_authenticated):
        try:
            token = request.headers['Authorization'].replace('Bearer ', '')
            cache.set(f'BLACKLIST_TOKEN_{token}', f'{token}')

            Logger().dispatch('INFO', __module_name__, 'LogoutResource.post',
                                   f'User {user_authenticated["uuid"]} logged out successfully')
            return {'message': messages.LOGOUT_SUCCESSFULLY}, 200

        except Exception as e:
            Logger().dispatch('CRITICAL', __module_name__, 'LogoutResource.post', str(e))
            return {'message': messages.INTERNAL_SERVER_ERROR}, 500


class ValidateTokenResource(Resource):

    @staticmethod
    @token_provider.verify_token
    def get(user_authenticated):
        try:
            user_schema = userschemas.UserGetSchema()
            user_data = user_schema.dump(user_authenticated)

            Logger().dispatch('INFO', __module_name__, 'ValidateTokenResource.get',
                                   f'Token by {user_authenticated["uuid"]} validated successfully')
            return {'user': user_data}, 200

        except Exception as e:
            Logger().dispatch('CRITICAL', __module_name__, 'ValidateTokenResource.get', str(e))
            return {'message': messages.INTERNAL_SERVER_ERROR}, 500


class ValidateAdminResource(Resource):
        @staticmethod
        @token_provider.verify_token
        @token_provider.admin_required
        def get(user_authenticated):
            try:
                user_schema = userschemas.UserGetSchema()
                user_data = user_schema.dump(user_authenticated)

                Logger().dispatch('INFO', __module_name__, 'ValidateAdminResource.get',
                                    f'User {user_authenticated["uuid"]} is admin')
                return {'user': user_data}, 200

            except Exception as e:
                Logger().dispatch('CRITICAL', __module_name__, 'ValidateAdminResource.get', str(e))
                return {'message': messages.INTERNAL_SERVER_ERROR}, 500


class ForgotPasswordResource(Resource):
    @staticmethod
    def post():
        try:
            try:
                data = request.get_json()
            except UnsupportedMediaType as e:
                Logger().dispatch('INFO', __module_name__, 'ForgotPasswordResource.post', str(e))
                return {'message': messages.UNSUPPORTED_MEDIA_TYPE}, 415
            except Exception as e:
                Logger().dispatch('INFO', __module_name__, 'ForgotPasswordResource.post', str(e))
                return {'message': messages.BAD_REQUEST}, 400

            schema_validate = validate_schema(userschemas.ForgotPasswordSchema(), data)
            if schema_validate:
                Logger().dispatch('INFO', __module_name__, 'ForgotPasswordResource.post',
                                       f'Schema validation error: {schema_validate}')
                return {'message': schema_validate}, 400

            user = UserModel.get_by_email(email=data['email'])

            if not user:
                Logger().dispatch('INFO', __module_name__, 'ForgotPasswordResource.post',
                                       f'User {data["email"]} not found')
                return {'message': messages.USER_NOT_FOUND}, 404

            token = token_provider.create_token(payload={'email': user.email})
            url = f'{config_env("API_GATEWAY_HOST")}/auth/users/reset-password/{token}/'

            payload = {
                "transaction_id": request.headers.get('X-TRANSACTION-ID'),
                "email": data['email'],
                "subject": 'Recovey Password',
                "template": f"<html><body><a href='{url}'>Clique aqui</a></body></html>"
            }

            Thread(target=KafkaService().producer,
                   args=(config_env('TOPIC_SEND_EMAIL_RECOVERY_PASSWORD'), user.uuid, payload,)).start()



            Logger().dispatch('INFO', __module_name__, 'ForgotPasswordResource.post',
                                   f'Email sent topic {config_env("TOPIC_SEND_EMAIL_RECOVERY_PASSWORD")}')
            return {'message': messages.EMAIL_SENT_SUCCESSFULLY}, 200

        except Exception as e:
            Logger().dispatch('CRITICAL', __module_name__, 'ForgotPasswordResource.post', str(e))
            return {'message': messages.INTERNAL_SERVER_ERROR}, 500


class ResetPasswordResource(Resource):
    @staticmethod
    def get(token):
        try:
            cache_token = cache.get(f'BLACKLIST_TOKEN_{token}')
            if cache_token:
                Logger().dispatch('INFO', __module_name__, 'ResetPasswordResource.get',
                                       f'Token {token} is blacklisted')
                return {'message': messages.TOKEN_IS_INVALID}, 401

            user_authenticated = token_provider.verify_token_email(token=token)
            if not user_authenticated:
                Logger().dispatch('INFO', __module_name__, 'ResetPasswordResource.get',
                                       f'Token {token} is invalid')
                return {'message': messages.TOKEN_IS_INVALID}, 401

            user = UserModel.get_by_email(email=user_authenticated['email'])

            if not user:
                Logger().dispatch('INFO', __module_name__, 'ResetPasswordResource.get',
                                       f'User {user_authenticated["email"]} not found')
                return {'message': messages.USER_NOT_FOUND}, 404

            if not user.email_valid:
                Logger().dispatch('INFO', __module_name__, 'ResetPasswordResource.get',
                                       f'User {user_authenticated["email"]} not validated')
                return {'message': messages.USER_NON_VALIDATED_EMAIL}, 400

            cache.set(f'BLACKLIST_TOKEN_{token}', token, timeout=60 * 60 * 24 * 7)

            user_schema = userschemas.UserGetSchema()
            user_data = user_schema.dump(user)

            return {'message': messages.USER_VALIDATED_SUCCESSFULLY}, 200

        except Exception as e:
            Logger().dispatch('CRITICAL', __module_name__, 'ResetPasswordResource.get', str(e))
            return {'message': messages.INTERNAL_SERVER_ERROR}, 500


class ValidateEmailResource(Resource):
    @staticmethod
    def get(token):
        try:
            cache_token = cache.get(f'BLACKLIST_TOKEN_{token}')
            if cache_token:
                Logger().dispatch('INFO', __module_name__, 'ValidateEmailResource.get',
                                       f'Token {token} is blacklisted')
                return {'message': messages.TOKEN_IS_INVALID}, 401

            user_authenticated = token_provider.verify_token_email(token=token)
            if not user_authenticated:
                Logger().dispatch('INFO', __module_name__, 'ValidateEmailResource.get',
                                       f'Token {token} is invalid')
                return {'message': messages.TOKEN_IS_INVALID}, 401

            user = UserModel.get_by_email(email=user_authenticated['email'])
            if not user:
                Logger().dispatch('INFO', __module_name__, 'ValidateEmailResource.get',
                                       f'User {user_authenticated["email"]} not found')
                return {'message': messages.USER_NOT_FOUND}, 404

            if user.email_valid:
                Logger().dispatch('INFO', __module_name__, 'ValidateEmailResource.get',
                                       f'User {user_authenticated["email"]} already validated')
                return {'message': messages.USER_ALREADY_VALIDATED}, 400

            try:
                UserModel.validate_email(user)
                Logger().dispatch('INFO', __module_name__, 'ValidateEmailResource.get',
                                       f'User {user_authenticated["email"]} validated successfully')
            except Exception as e:
                Logger().dispatch('CRITICAL', __module_name__, 'ValidateEmailResource.get', str(e))
                return {'message': messages.INTERNAL_SERVER_ERROR}, 500

            cache.set(f'BLACKLIST_TOKEN_{token}', token, timeout=60 * 60 * 24 * 7)

            user_schema = userschemas.UserGetSchema()
            user_data = user_schema.dump(user)

            return {'message': messages.USER_VALIDATED_SUCCESSFULLY}, 200

        except Exception as e:
            Logger().dispatch('CRITICAL', __module_name__, 'ValidateEmailResource.get', str(e))
            return {'message': messages.INTERNAL_SERVER_ERROR}, 500


class SendEmailValidationResource(Resource):
    @staticmethod
    def post():
        try:
            try:
                data = request.get_json()
            except UnsupportedMediaType as e:
                Logger().dispatch('INFO', __module_name__, 'SendEmailValidationResource.post', str(e))
                return {'message': messages.UNSUPPORTED_MEDIA_TYPE}, 415
            except Exception as e:
                Logger().dispatch('INFO', __module_name__, 'SendEmailValidationResource.post', str(e))
                return {'message': messages.BAD_REQUEST}, 400

            schema_validate = validate_schema(userschemas.UserSendEmailValidationSchema(), data)

            if schema_validate:
                Logger().dispatch('INFO', __module_name__, 'SendEmailValidationResource.post',
                                       f'Schema validation error: {schema_validate}')
                return {'message': schema_validate}, 400

            user = UserModel.get_by_email(email=data['email'])

            if not user:
                Logger().dispatch('INFO', __module_name__, 'SendEmailValidationResource.post',
                                       f'User {data["email"]} not found')
                return {'message': messages.USER_NOT_FOUND}, 404

            if user.email_valid:
                Logger().dispatch('INFO', __module_name__, 'SendEmailValidationResource.post',
                                       f'User {data["email"]} already validated')
                return {'message': messages.USER_ALREADY_VALIDATED}, 400

            token = token_provider.create_token(payload={'email': user.email})
            url = f'{config_env("API_GATEWAY_HOST")}/auth/users/validate-email/{token}/'

            payload = {
                "transaction_id": request.headers.get('X-TRANSACTION-ID'),
                "email": data['email'],
                "subject": 'Account Validation',
                "template": f"<html><body><a href='{url}'>Clique aqui</a></body></html>"
            }

            Thread(target=KafkaService().producer,
                   args=(config_env('TOPIC_SEND_EMAIL_VALIDATION_ACCOUNT'), user.uuid, payload,)).start()

            Logger().dispatch('INFO', __module_name__, 'SendEmailValidationResource.post',
                                   f'Email sent topic {config_env("TOPIC_SEND_EMAIL_VALIDATION_ACCOUNT")}')
            return {'message': messages.EMAIL_SENT_SUCCESSFULLY}, 200

        except Exception as e:
            Logger().dispatch('CRITICAL', __module_name__, 'SendEmailValidationResource.post', str(e))
            return {'message': messages.INTERNAL_SERVER_ERROR}, 500
