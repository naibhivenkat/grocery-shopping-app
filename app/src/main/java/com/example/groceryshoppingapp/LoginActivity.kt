package com.example.groceryshoppingapp

import android.annotation.SuppressLint
import android.content.Intent
import android.os.Bundle
import android.util.Log
import android.view.View
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import com.example.groceryshoppingapp.models.LoginRequest
import com.example.groceryshoppingapp.models.LoginResponse
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.utils.SessionManager
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class LoginActivity : AppCompatActivity() {

    private lateinit var usernameEdit: EditText
    private lateinit var passwordEdit: EditText
    private lateinit var loginButton: Button
    private lateinit var registerText: TextView
    private lateinit var titleText: TextView
    private lateinit var errorText: TextView
    private lateinit var forgotPasswordText: TextView
    private lateinit var helpText: TextView
    private lateinit var progressBar: ProgressBar


    private val appRole by lazy { BuildConfig.APP_ROLE.lowercase() }

    override fun onCreate(savedInstanceState: Bundle?) {
        LanguageManager.applySavedLanguage(this)
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_login)

        titleText = findViewById(R.id.tv_login_title)
        usernameEdit = findViewById(R.id.et_username)
        passwordEdit = findViewById(R.id.et_password)
        loginButton = findViewById(R.id.btn_login)
        registerText = findViewById(R.id.tv_register)
        errorText = findViewById(R.id.tv_error_message)
        forgotPasswordText = findViewById(R.id.tv_forgot_password)
        helpText = findViewById(R.id.tv_help)
        progressBar = findViewById(R.id.progress_bar)

        titleText.text = when (appRole) {
            "customer" -> getString(R.string.customer_login)
            "shopowner" -> getString(R.string.shop_owner_login)
            else -> getString(R.string.login)
        }

        loginButton.setOnClickListener {
            val username = usernameEdit.text.toString().trim()
            val password = passwordEdit.text.toString().trim()
            errorText.visibility = View.GONE

            if (username.isEmpty() || password.isEmpty()) {
                errorText.text = getString(R.string.enter_username_password)
                errorText.visibility = View.VISIBLE
                return@setOnClickListener
            }

            doLogin(username, password)
        }

        registerText.setOnClickListener {
//            startActivity(Intent(this, RegisterActivity::class.java))
            checkServerBeforeRegister()
        }


        forgotPasswordText.setOnClickListener {
            startActivity(Intent(this, ForgotPasswordActivity::class.java))
        }

        helpText.setOnClickListener {
            startActivity(Intent(this, HelpActivity::class.java))
        }
    }

    private fun doLogin(username: String, password: String) {
        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)

        // Show progress bar and disable login button
        progressBar.visibility = View.VISIBLE
        loginButton.isEnabled = false
        errorText.visibility = View.GONE

        api.login(LoginRequest(username, password)).enqueue(object : Callback<LoginResponse> {

            @SuppressLint("StringFormatInvalid")
            override fun onResponse(call: Call<LoginResponse>, response: Response<LoginResponse>) {
                progressBar.visibility = View.GONE
                loginButton.isEnabled = true

                try {
                    val loginResponse = response.body()

                    when {
                        !response.isSuccessful -> {
                            // HTTP errors like 500, 404
                            errorText.text = "Server is temporarily unavailable. Please try later."
                            errorText.visibility = View.VISIBLE
                        }
                        loginResponse == null -> {
                            // Null or malformed response
                            errorText.text = "Server is temporarily unavailable. Please try later."
                            errorText.visibility = View.VISIBLE
                        }
                        loginResponse.success != true -> {
                            // Success=false → invalid credentials
                            errorText.text = getString(R.string.invalid_username_password)
                            errorText.visibility = View.VISIBLE
                        }
                        else -> {
                            // ✅ Successful login
                            val user = loginResponse.user
                            val loginRole = user?.role?.lowercase()?.trim()

                            // Save auth token if present
                            loginResponse.token?.let { token ->
                                SessionManager.setAuthToken(this@LoginActivity, token)
                            }

                            // Role mismatch check
                            if (loginRole != appRole) {
                                errorText.text = getString(R.string.role_mismatch, appRole.replaceFirstChar { it.uppercase() })
                                errorText.visibility = View.VISIBLE
                                return
                            }

                            // Save session and profile
                            SessionManager.saveLogin(this@LoginActivity, user?.username ?: "", loginRole ?: "")
                            SessionManager.saveUserProfile(
                                this@LoginActivity,
                                user?.fullName ?: "",
                                user?.address ?: "",
                                user?.phone ?: "",
                                user?.email ?: "",
                                user?.location ?: "",
                                user?.photoBase64 ?: ""
                            )
                            user?.customerId?.let { SessionManager.setCustomerId(this@LoginActivity, it) }
                            user?.shopkeeperId?.let { SessionManager.setShopkeeperId(this@LoginActivity, it) }

                            // Save shop info if exists
                            user?.shop?.id?.let { shopDocId ->
                                SessionManager.setShopId(this@LoginActivity, shopDocId)
                                SessionManager.setShopInfo(this@LoginActivity, shopDocId, user.shop?.name ?: "")
                            }
                            val hasItems = user?.hasItems ?: true
                            SessionManager.setHasItemsAdded(this@LoginActivity, hasItems)

                            // Redirect based on role and shop/items
                            when (loginRole) {
                                "customer" -> startActivity(Intent(this@LoginActivity, CustomerHomeActivity::class.java))
                                "shopowner" -> {
                                    if (SessionManager.hasShopWithItems(this@LoginActivity)) {
                                        startActivity(Intent(this@LoginActivity, ShopOwnerDashboardActivity::class.java))
                                    } else {
                                        startActivity(Intent(this@LoginActivity, AddItemsActivity::class.java))
                                    }
                                }
                                else -> {
                                    errorText.text = getString(R.string.unknown_user_role)
                                    errorText.visibility = View.VISIBLE
                                    return
                                }
                            }
                            finish()
                        }
                    }
                } catch (e: Exception) {
                    Log.e("LoginDebug", "Exception in onResponse", e)
                    errorText.text = "Server is temporarily unavailable. Please try later."
                    errorText.visibility = View.VISIBLE
                }
            }

            override fun onFailure(call: Call<LoginResponse>, t: Throwable) {
                progressBar.visibility = View.GONE
                loginButton.isEnabled = true

                val message = when (t) {
                    is java.net.UnknownHostException -> "Server is offline. Please check your internet connection."
                    is java.net.ConnectException -> "Cannot connect to server. Try again later."
                    is java.net.SocketTimeoutException -> "Server timed out. Please try again."
                    else -> "Login failed: ${t.localizedMessage ?: "Unknown error"}"
                }
                errorText.text = message
                errorText.visibility = View.VISIBLE
            }
        })
    }


    private fun checkServerBeforeRegister() {
        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)

        // Show progress & disable register click
        progressBar.visibility = View.VISIBLE
        registerText.isEnabled = false

        api.healthCheck().enqueue(object : Callback<Map<String, String>> {
            override fun onResponse(
                call: Call<Map<String, String>>,
                response: Response<Map<String, String>>
            ) {
                progressBar.visibility = View.GONE
                registerText.isEnabled = true

                if (response.isSuccessful) {
                    // Server is active → proceed to RegisterActivity
                    startActivity(Intent(this@LoginActivity, RegisterActivity::class.java))
                } else {
                    Toast.makeText(
                        this@LoginActivity,
                        "Server is temporarily unavailable. Please try later.",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            }

            override fun onFailure(call: Call<Map<String, String>>, t: Throwable) {
                progressBar.visibility = View.GONE
                registerText.isEnabled = true
                Toast.makeText(
                    this@LoginActivity,
                    "Server is offline. Please check your connection.",
                    Toast.LENGTH_SHORT
                ).show()
            }
        })
    }
}
