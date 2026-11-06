#!/usr/bin/python3

import tempfile
from contextlib import contextmanager
from unittest.mock import Mock, call, patch

import pytest

from osbuild import testutil

STAGE_NAME = "org.osbuild.bootc.install-to-filesystem"


@pytest.fixture(name="mocked_named_tmp")
def mocked_named_tmp_fixture():
    fake_named_tmp = Mock()
    fake_named_tmp.name = "/tmp/fake-named-tmpfile-name"
    with patch("tempfile.NamedTemporaryFile", return_value=fake_named_tmp):
        yield


@pytest.fixture(name="mocked_temp_dir")
def mocked_temp_dir_fixture(tmp_path):
    @contextmanager
    def _tmp_dir():
        yield tmp_path
    with patch("tempfile.TemporaryDirectory", side_effect=_tmp_dir):
        yield tmp_path


FAKE_INPUTS = {
    "images": {
        "path": "/input/images/path",
        "data": {
            "archives": {
                "filename": {
                    "format": "oci-archive",
                    "name": "some-img-name",
                },
            },
        },
    }
}


@pytest.mark.parametrize("options,expected_err", [
    # good
    ({}, ""),
    ({"initialize-var-mounts": True, "defer-var": True}, ""),
    ({"initialize-var-mounts": False, "defer-var": False}, ""),
    # bad
    ({"initialize-var-mounts": "yes"}, "'yes' is not of type 'boolean'"),
    ({"defer-var": "yes"}, "'yes' is not of type 'boolean'"),
])
def test_bootc_install_to_fs_schema_validation(stage_schema, options, expected_err):
    test_input = {
        "type": STAGE_NAME,
        "options": options,
    }
    res = stage_schema.validate(test_input)

    if expected_err == "":
        assert res.valid is True, f"err: {[e.as_dict() for e in res.errors]}"
    else:
        assert res.valid is False
        testutil.assert_jsonschema_error_contains(res, expected_err, expected_num_errs=1)


@pytest.mark.parametrize("options,expected_args", [
    ({}, []),
    # root-ssh
    ({"root-ssh-authorized-keys": []}, []),
    ({"root-ssh-authorized-keys": ["ssh-key"]}, ["--root-ssh-authorized-keys", "/tmp/fake-named-tmpfile-name"]),
    ({"root-ssh-authorized-keys": ["key1", "key2"]}, ["--root-ssh-authorized-keys", "/tmp/fake-named-tmpfile-name"]),
    # kernel args
    ({"kernel-args": []}, []),
    ({"kernel-args": ["console=ttyS0"]}, ["--karg", "console=ttyS0"]),
    ({"kernel-args": ["arg1", "arg2"]}, ["--karg", "arg1", "--karg", "arg2"]),
    # stateroot
    ({"stateroot": ""}, []),
    ({"stateroot": "default1"}, ["--stateroot", "default1"]),
    # root-mount-spec
    ({"root-mount-spec": ""}, ["--root-mount-spec="]),
    ({"root-mount-spec": "subvol@root"}, ["--root-mount-spec", "subvol@root"]),
    # boot-mount-spec
    ({"boot-mount-spec": ""}, ["--boot-mount-spec="]),
    ({"boot-mount-spec": "/dev/sda1"}, ["--boot-mount-spec", "/dev/sda1"]),
    # bootupd-skip-boot-uuid
    ({"bootupd-skip-boot-uuid": False}, []),
    ({"bootupd-skip-boot-uuid": True}, ["--bootupd-skip-boot-uuid"]),
    # bootloader
    ({"bootloader": "none"}, ["--bootloader", "none"]),
    ({"bootloader": "systemd"}, ["--bootloader", "systemd"]),
    ({"bootloader": "grub"}, ["--bootloader", "grub"]),
    # composefs
    ({"composefs": False}, []),
    ({"composefs": True}, ["--composefs-backend"]),
    # initialize-var-mounts
    ({"initialize-var-mounts": False}, []),
    ({"initialize-var-mounts": True}, ["--initialize-var-mounts"]),
    # defer-var
    ({"defer-var": False}, []),
    ({"defer-var": True}, ["--defer-var"]),
    # all
    ({"root-ssh-authorized-keys": ["key1", "key2"],
      "kernel-args": ["arg1", "arg2"],
      "target-imgref": "quay.io/img/ref",
      "stateroot": "/some/stateroot",
      "root-mount-spec": "root-mount-spec",
      "boot-mount-spec": "boot-mount-spec",
      "bootupd-skip-boot-uuid": True,
      "initialize-var-mounts": True,
      "defer-var": True,
      },
     ["--root-ssh-authorized-keys", "/tmp/fake-named-tmpfile-name",
      "--karg", "arg1", "--karg", "arg2",
      "--target-imgref", "quay.io/img/ref",
      "--stateroot", "/some/stateroot",
      "--root-mount-spec", "root-mount-spec",
      "--boot-mount-spec", "boot-mount-spec",
      "--bootupd-skip-boot-uuid",
      "--initialize-var-mounts",
      "--defer-var",
      ],
     ),
])
@patch("subprocess.run")
@patch("subprocess.check_call")
def test_bootc_install_to_fs(mock_check_call, mock_run, mocked_named_tmp, mocked_temp_dir, stage_module, options, expected_args):  # pylint: disable=unused-argument
    inputs = {
        "images": {
            "path": "/input/images/path",
            "data": {
                "archives": {
                    "filename": {
                        "format": "oci-archive",
                        "name": "some-img-name",
                    },
                },
            },
        },
    }
    paths = {
        "mounts": "/path/to/mounts",
    }

    stage_module.main(options, inputs, paths)

    assert len(mock_run.call_args_list) == 1
    args, kwargs = mock_run.call_args_list[0]
    assert args == (
        ["bootc", "install", "to-filesystem",
         "--source-imgref", f"oci-archive:{mocked_temp_dir}/image",
         "--skip-fetch-check", "--generic-image",
         ] + expected_args + ["/path/to/mounts"],
    )
    assert kwargs["check"] is True
    assert kwargs["env"]["BOOTC_SKIP_SELINUX_HOST_CHECK"] == "true"

    assert mock_check_call.call_count == 4
    mock_check_call.assert_has_calls([
        call(['mount', '-t', 'devtmpfs', 'devtmpfs', '/dev/']),
        call(['mount', '-t', 'tmpfs', 'tmpfs', '/dev/shm']),
        call(['umount', '/dev/shm']),
        call(['umount', '/dev/']),
    ])


@patch("subprocess.run")
@patch("subprocess.check_call")
def test_bootc_install_to_fs_write_root_ssh_keys(_mock_check_call, mock_run, stage_module):  # pylint: disable=unused-argument
    paths = {
        "mounts": "/path/to/mounts",
    }
    options = {
        "root-ssh-authorized-keys": ["key1", "key2"],
    }

    named_tmp = tempfile.NamedTemporaryFile(delete=False)
    with patch("tempfile.NamedTemporaryFile", return_value=named_tmp):
        stage_module.main(options, FAKE_INPUTS, paths)
        with open(named_tmp.name, encoding="utf8") as fp:
            assert "key1\nkey2\n" == fp.read()
