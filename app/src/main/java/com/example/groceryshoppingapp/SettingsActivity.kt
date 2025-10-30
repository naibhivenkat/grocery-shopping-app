package com.example.groceryshoppingapp

import android.app.AlertDialog
import android.app.DownloadManager
import android.content.*
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import com.example.groceryshoppingapp.utils.SessionManager
import com.example.groceryshoppingapp.BuildConfig
import okhttp3.*
import org.json.JSONObject
import java.io.File
import java.io.IOException

// Make sure to import this for Android 13+ receiver registration!
import android.content.Context.RECEIVER_NOT_EXPORTED

class SettingsActivity : AppCompatActivity() {

    private lateinit var tvUsername: TextView
    private lateinit var tvRole: TextView

    private lateinit var btnChangePassword: Button
    private lateinit var btnChangeLanguage: Button
    private lateinit var btnSoftwareInfo: Button
    private lateinit var btnLogout: Button
    private lateinit var btnBack: ImageButton

    private val client = OkHttpClient()
    private var downloadId: Long = -1L
    private val onDownloadComplete: BroadcastReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            val id = intent?.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1)
            if (id == downloadId) {
                val file = File(
                    Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
                    "groceryapp-latest.apk"
                )
                if (file.exists()) {
                    val apkUri: Uri = FileProvider.getUriForFile(
                        this@SettingsActivity,
                        "${packageName}.provider",
                        file
                    )
                    val installIntent = Intent(Intent.ACTION_VIEW).apply {
                        setDataAndType(apkUri, "application/vnd.android.package-archive")
                        flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION
                    }
                    startActivity(installIntent)
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)

        // Proper receiver registration for all Android versions
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(
                onDownloadComplete,
                IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE),
                RECEIVER_NOT_EXPORTED
            )
        } else {
            @Suppress("DEPRECATION")
            registerReceiver(
                onDownloadComplete,
                IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE)
            )
        }

        tvUsername = findViewById(R.id.tv_profile_username)
        tvRole = findViewById(R.id.tv_profile_role)
        btnChangePassword = findViewById(R.id.btn_change_password)
        btnChangeLanguage = findViewById(R.id.btn_change_language)
        btnSoftwareInfo = findViewById(R.id.btn_software_info)
        btnLogout = findViewById(R.id.btn_logout)
        btnBack = findViewById(R.id.btn_back)

        tvUsername.text = "Username: ${SessionManager.getUsername(this)}"
        tvRole.text = "Role: ${SessionManager.getRole(this)?.replaceFirstChar { it.uppercase() }}"

        btnChangePassword.setOnClickListener {
            startActivity(Intent(this, ChangePasswordActivity::class.java))
        }

        btnChangeLanguage.setOnClickListener {
            startActivity(Intent(this, LanguageSelectionActivity::class.java))
        }

        btnLogout.setOnClickListener {
            SessionManager.logout(this)
            startActivity(Intent(this, LoginActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
            })
            finish()
        }

        btnBack.setOnClickListener { finish() }

        btnSoftwareInfo.setOnClickListener { showSoftwareInfoDialog() }
    }

    // Show dialog with version info & check for update button
    private fun showSoftwareInfoDialog() {
        val dialogView = layoutInflater.inflate(R.layout.software_info_dialog, null)
        val tvVersion = dialogView.findViewById<TextView>(R.id.tv_current_version)
        tvVersion.text = "Current Version: ${BuildConfig.VERSION_NAME}"

        val dialog = AlertDialog.Builder(this)
            .setView(dialogView)
            .setCancelable(true)
            .create()

        dialogView.findViewById<Button>(R.id.btn_check_update).setOnClickListener {
            checkForUpdates { latestName, apkUrl, sizeBytes ->
                dialog.dismiss()
                showUpdatePopup(latestName, apkUrl, sizeBytes)
            }
        }
        dialogView.findViewById<Button>(R.id.btn_info_close).setOnClickListener {
            dialog.dismiss()
        }

        dialog.show()
    }

    // Show update popup with info, size, download/cancel buttons
    private fun showUpdatePopup(latestVersion: String, apkUrl: String, apkSize: Long) {
        val dialogView = layoutInflater.inflate(R.layout.update_dialog, null)
        dialogView.findViewById<TextView>(R.id.tv_latest_version).text =
            "Latest Version: $latestVersion"
        dialogView.findViewById<TextView>(R.id.tv_apk_size).text =
            "APK Size: ${formatSize(apkSize)}"

        val dialog = AlertDialog.Builder(this)
            .setView(dialogView)
            .setCancelable(true)
            .create()

        dialogView.findViewById<Button>(R.id.btn_download).setOnClickListener {
            downloadApk(apkUrl)
            dialog.dismiss()
        }
        dialogView.findViewById<Button>(R.id.btn_cancel).setOnClickListener {
            dialog.dismiss()
        }

        dialog.show()
    }

    // Check for updates using your backend, show popup if update available
    private fun checkForUpdates(callback: (String, String, Long) -> Unit) {
        val request = Request.Builder()
            //.url("https://grocery-shopping-app-yyqx.onrender.com/check_update")
            .url("https://grocery-backend-956424262985.asia-south1.run.app/check_update")
            .build()
        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                runOnUiThread {
                    Toast.makeText(this@SettingsActivity, "Failed to check updates.", Toast.LENGTH_SHORT).show()
                }
            }

            override fun onResponse(call: Call, response: Response) {
                val body = response.body?.string()
                try {
                    val json = JSONObject(body ?: "{}")
                    val latestVersionCode = json.optInt("versionCode", -1)
                    val latestVersionName = json.optString("versionName", "")
                    val apkUrl = json.optString("apkUrl", "")
                    val apkSize = json.optLong("apkSize", 0L)
                    val currentVersion = BuildConfig.VERSION_CODE

                    runOnUiThread {
                        if (latestVersionCode > currentVersion) {
                            callback(latestVersionName, apkUrl, apkSize)
                        } else {
                            Toast.makeText(this@SettingsActivity, "App is up to date", Toast.LENGTH_SHORT).show()
                        }
                    }
                } catch (e: Exception) {
                    runOnUiThread {
                        Toast.makeText(this@SettingsActivity, "Could not retrieve update info", Toast.LENGTH_LONG).show()
                    }
                }
            }
        })
    }

    // Start downloading APK
    private fun downloadApk(apkUrl: String) {
        val request = DownloadManager.Request(Uri.parse(apkUrl))
            .setTitle("Downloading Update")
            .setDescription("Please wait...")
            .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, "groceryapp-latest.apk")
            .setMimeType("application/vnd.android.package-archive")
        val manager = getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
        downloadId = manager.enqueue(request)
        Toast.makeText(this, "Downloading update...", Toast.LENGTH_SHORT).show()
    }

    // Format file size nicely
    private fun formatSize(size: Long): String {
        val kb = size / 1024
        val mb = kb / 1024
        return if (mb > 0) "$mb MB" else if (kb > 0) "$kb KB" else "$size Bytes"
    }

    override fun onDestroy() {
        super.onDestroy()
        unregisterReceiver(onDownloadComplete)
    }
}
