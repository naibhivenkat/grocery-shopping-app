package com.example.groceryshoppingapp

import android.annotation.SuppressLint
import android.content.Intent
import android.os.Bundle
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
            startActivity(Intent(this, RegisterActivity::class.java))
        }
    }

    private fun doLogin(username: String, password: String) {
        val api = RetrofitClient.instance.create(ApiService::class.java)
        api.login(LoginRequest(username, password)).enqueue(object : Callback<LoginResponse> {
            @SuppressLint("StringFormatInvalid")
            override fun onResponse(call: Call<LoginResponse>, response: Response<LoginResponse>) {
                val loginResponse = response.body()

                if (response.isSuccessful && loginResponse?.success == true) {
                    val user = loginResponse.user
                    val loginRole = user?.role?.lowercase()?.trim()

                    // Block login if role does not match build flavor
                    if (loginRole != appRole) {
                        errorText.text = getString(
                            R.string.role_mismatch,
                            appRole.replaceFirstChar { it.uppercase() }
                        )
                        errorText.visibility = View.VISIBLE
                        return
                    }

                    // Save login + profile
                    SessionManager.saveLogin(this@LoginActivity, user?.username ?: "", loginRole ?: "")
                    SessionManager.saveUserProfile(
                        context = this@LoginActivity,
                        fullName = user?.fullName ?: "",
                        address = user?.address ?: "",
                        phone = user?.phone ?: "",
                        email = user?.email ?: "",
                        location = user?.location ?: "",
                        photoBase64 = user?.photoBase64 ?: ""
                    )

                    // First-time language selection
                    if (!SessionManager.isLanguageSelected(this@LoginActivity)) {
                        val langIntent = Intent(this@LoginActivity, LanguageSelectionActivity::class.java)
                        langIntent.putExtra("pendingRole", loginRole)
                        langIntent.putExtra("shopkeeperId", user?.shopkeeperId ?: "")
                        langIntent.putExtra("customerId", user?.customerId ?: "")
                        startActivity(langIntent)
                        finish()
                        return
                    }

                    when (loginRole) {
                        "customer" -> {
                            user?.customerId?.let { customerId ->
                                SessionManager.setCustomerId(this@LoginActivity, customerId)
                                startActivity(Intent(this@LoginActivity, CustomerHomeActivity::class.java))
                                finish()
                            }
                        }

                        "shopowner" -> {
                            user?.shopkeeperId?.let { shopkeeperId ->
                                SessionManager.setShopkeeperId(this@LoginActivity, shopkeeperId)

                                // ✅ Treat null shopExists as first-time
                                val hasShop = user.shopExists == true && user.shop != null

                                if (hasShop) {
                                    // Shop exists → save info and go to dashboard
                                    val shop = user.shop!!
                                    SessionManager.setShopId(this@LoginActivity, shop.id)
                                    SessionManager.setShopInfo(this@LoginActivity, shop.id, shop.name)
                                    startActivity(Intent(this@LoginActivity, ShopOwnerDashboardActivity::class.java))
                                    finish()
                                } else {
                                    // First-time → redirect to CreateShopActivity
                                    val intent = Intent(this@LoginActivity, CreateShopActivity::class.java)
                                    intent.putExtra("shopkeeperId", shopkeeperId)
                                    startActivity(intent)
                                    finish()
                                }
                            }
                        }

                        else -> {
                            errorText.text = getString(R.string.unknown_user_role)
                            errorText.visibility = View.VISIBLE
                        }
                    }
                } else {
                    errorText.text = getString(R.string.invalid_username_password)
                    errorText.visibility = View.VISIBLE
                }
            }

            override fun onFailure(call: Call<LoginResponse>, t: Throwable) {
                errorText.text = "Login failed: ${t.localizedMessage ?: t.message ?: "Unknown error"}"
                errorText.visibility = View.VISIBLE
            }
        })
    }
}
